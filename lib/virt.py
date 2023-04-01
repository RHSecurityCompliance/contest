"""
Provides utilities for installing, snapshotting and managing Libvirt-based
virtual machines.

Quick Terminology:
 - host: system that runs VMs (a.k.a. hypervisor)
 - guest: the VM itself
 - domain: libvirt's terminology for a VM
 - "host": guest translated to Czech :)

The host-related functionality is mainly installing libvirt + deps.

The guest-related functionality consists of:
  1) Installing guests (virt-install from URL)
  2) Preparing guests for snapshotting (booting up, taking RAM image)
  3) Snapshotting guests (repeatedly restoring, using, throwing away)

There is a Guest() class, which represents a guest with a specific name (used
for its domain name). Aside from doing (1) and (2), an instance of Guest can
be used in two ways, both using a context manager ('g' is an instance):
   - g.snapshotted()
     - Assumes (1) and (2) were done, creates a snapshot and restores the guest
       from its RAM image, waits for ssh.
     - Stops the guest and deletes the snapshot on __exit__
   - g.booted()
     - Assumes (1) was done and just boots and waits for ssh.

Any host yum.repos.d repositories are given to Anaconda via kickstart 'repo'
upon guest installation. Only baseurl is supported for now, Fedora won't work.

Step (1) can be replaced by importing a pre-existing ImageBuilder image, with
(2) and (3), or Guest() usage, remaining unaffected / compatible.

Installation customization can be done via g.install() arguments, such as by
instantiating Kickstart() in the test itself, modifying it, and passing the
instance to g.install().

This module also hacks PermitRootLogin=yes in the sshd sysconfig file
(not checked by oscap) instead of using unprivileged + sudo, because there
are more oscap rules breaking NOPASSWD sudo and needing special nonstandard
sudo-related authentication (cvtsudoers), .. than the 1 rule for sshd.

Example using snapshots:

    import virt

    virt.setup_host()
    g = virt.Guest('gui')

    # reuse if it already exists from previous tests, reinstall if not
    if not g.can_be_snapshotted():
        g.install()
        g.prepare_for_snapshot()

    with g.snapshotted():
        state = g.ssh('ls', '/root', capture=True)
        print(state.stdout)
        if state.returncode != 0:
            report_failure()

    with g.snapshotted():
        out = g.ssh(...)

Example using plain one-time-use guest:

    import virt
    import atexit

    virt.setup_host()
    gm = virt.Guest()

    ks = virt.Kickstart()
    ks.add_post('some test-specific stuff')
    g.install(kickstart=ks)
    atexit.register(g.remove)

    with g.booted():
        g.ssh( ... )
        g.ssh( ... )
"""

import os
import sys
import re
import logging
import socket
import time
import inspect
import builtins
import subprocess
import textwrap
import contextlib
import shutil
import tempfile
import requests
import configparser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
#from . import util

import util
import versions

_log = logging.getLogger(__name__).debug

GUEST_NAME = 'contest-ssg'
GUEST_LOGIN_PASS = 'c0Nt3st-SSG,pass'
GUEST_SSH_USER = 'root'

GUEST_IMG_DIR = '/var/lib/libvirt/images'

# don't rely on 'default' being sane, define a new STP-less network
NETWORK_NAME = 'contest-ssg-net'
NETWORK_PREFIX = '192.168.121'

KICKSTART_TEMPLATE = f'''\
lang en_US.UTF-8
keyboard --vckeymap us
network --onboot yes --bootproto dhcp
rootpw {GUEST_LOGIN_PASS}
firstboot --disable
selinux --enforcing
timezone --utc Europe/Prague
bootloader --append="console=ttyS0,115200 mitigations=off"
reboot
zerombr
clearpart --all --initlabel

# commonly used partitions by some content profiles
#autopart --type=plain --nohome
part /boot --size=700
part / --size=1000
part /home --size=100
part /var --size=6000
part /var/log --size=1000
part /var/log/audit --size=1000
part /var/tmp --size=1000
part /srv --size=100
part /opt --size=100
part /tmp --size=1000
part /usr --size=8000

%post
# broken by something adding $CRYPTO_POLICY
#sed '/^ExecStart=.*\/sshd /s/$/ -oPermitRootLogin=yes/' \\
#  -i /usr/lib/systemd/system/sshd.service
echo 'OPTIONS=-oPermitRootLogin=yes' >> /etc/sysconfig/sshd
%end

%post --erroronfail
# would have been done by subscription-manager
rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release
dnf -y makecache || yum -y makecache
%end'''

KICKSTART_PACKAGES = [
    'openscap-scanner',
    'scap-security-guide',
]

# as byte-strings
INSTALL_FAILURES = [
    b"org.fedoraproject.Anaconda.Addons.OSCAP.*: The installation should be aborted.",
    b"There was an error running the kickstart script",
]

PIPE = subprocess.PIPE
DEVNULL = subprocess.DEVNULL


#
# host system preparation - installing libvirt, setting it up, etc.
#

def check_host_virt():
    """
    Return True if the host has HW-accelerated virtualization support (HVM).
    Else return False.
    """
    with open('/proc/cpuinfo') as f:
        cpuinfo = f.read()
    for virt_type in ['vmx', 'svm']:
        if re.search(f'\nflags\t+:.* {virt_type}( |$)', cpuinfo):
            return True
    return False


def setup_host():
    if not check_host_virt():
        raise RuntimeError("host has no HVM virtualization support")

    dnf = 'dnf' if shutil.which('dnf') else 'yum'

    host_pkgs = [
        'libvirt-daemon-driver-qemu',
        'libvirt-daemon-driver-storage-core',
        'libvirt-daemon-driver-network',
        #'libvirt-daemon-config-network',
        'firewalld',  # needed for virtual networks to work (?)
        'qemu-kvm',
        'libvirt-client',
        'virt-install',
    ]
    # optimize for speed - avoid starting a dnf transaction if everything
    # is already installed
    ret = subprocess.run(['rpm', '--quiet', '-q'] + host_pkgs)
    if ret.returncode != 0:
        _log("installing libvirt + qemu")
        cmd = [dnf, '-y', '--nogpgcheck', '--setopt=install_weak_deps=False', 'install']
        subprocess.run(cmd + host_pkgs, check=True)
        # free up some disk space
        subprocess.run([dnf, 'clean', 'packages'], check=True)

    _log("enabling libvirtd")
    subprocess.run(['systemctl', 'enable', '--now', 'libvirtd'], check=True)

    net_xml = textwrap.dedent(f'''\
        <network>
          <name>{NETWORK_NAME}</name>
          <forward mode='nat'/>
          <bridge stp='off' delay='0'/>
          <ip address='{NETWORK_PREFIX}.1' netmask='255.255.255.0'>
            <dhcp>
              <range start='{NETWORK_PREFIX}.2' end='{NETWORK_PREFIX}.254'>
                <lease expiry='0' unit='hours'/>
              </range>
            </dhcp>
          </ip>
        </network>''')
    ret = virsh('net-info', NETWORK_NAME, stdout=DEVNULL, stderr=DEVNULL)
    if ret.returncode != 0:
        _log(f"defining libvirt network: {NETWORK_NAME}")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml') as f:
            f.write(net_xml)
            f.flush()
            virsh('net-define', f.name, check=True)
        virsh('net-autostart', NETWORK_NAME, check=True)
        virsh('net-start', NETWORK_NAME, check=True)


#
# Anaconda Kickstart related customizations
#

class Kickstart:
    def __init__(self, kickstart=KICKSTART_TEMPLATE, packages=KICKSTART_PACKAGES):
        self.log = logging.getLogger(f'{__name__}.{self.__class__.__name__}').debug
        self.ks = kickstart
        self.appends = []
        self.packages = packages

    def _assemble_ks(self):
        appends_block = '\n'.join(self.appends)
        packages_block = '\n'.join(self.packages)
        packages_block = f'%packages\n{packages_block}\n%end'
        return '\n\n'.join([self.ks, appends_block, packages_block])
        # self.ks + self.packages + self.scripts

    @contextlib.contextmanager
    def to_tmpfile(self):
        final_ks = self._assemble_ks()
        self.log(f"writing:\n{textwrap.indent(final_ks, '    ')}")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ks.cfg') as f:
            f.write(final_ks)
            f.flush()
            yield Path(f.name)
            # backing file of f is deleted when we exit this scope

    def append(self, content):
        """Append arbitrary string content to the kickstart template."""
        self.appends.append(content)

    def add_post(self, content):
        new = (f'%post --interpreter=/bin/bash --erroronfail\n'
               'set -xe; exec >/dev/tty 2>&1\n' + content + '\n%end')
        self.append(new)

    def add_packages(self, pkgs):
        self.packages += pkgs

    def add_repo(self, name, url, install=True):
        new = f'repo --name={name} --baseurl={url}'
        new += ' --install' if install else ''
        self.appends.append(new)

    def add_host_repos(self):
        for reponame, url in host_dnf_repos():
            self.add_repo(reponame, url)

    def add_oscap(self, keyvals):
        """Append an OSCAP addon section, with key=value pairs from 'keyvals'."""
        lines = '\n'.join(f'  {k} = {v}' for k, v in keyvals.items())
        self.append(f'%addon org_fedora_oscap\n{lines}\n%end')

    def add_authorized_key(self, pubkey, homedir='/root', owner='root'):
        script = textwrap.dedent(f'''\
            mkdir -m 0700 -p {homedir}/.ssh
            cat >> {homedir}/.ssh/authorized_keys <<EOF
            {pubkey}
            EOF
            chmod 0600 {homedir}/.ssh/authorized_keys
            chown {owner} -R {homedir}/.ssh''')
        self.add_post(script)


#
# all user-visible guest operations, from installation to ssh
#

class Guest:
    """
    When instantiated, represents a guest (VM).

    Set a 'tag' (string) to a unique name you would like to share across tests
    that use snapshots - the .can_be_snapshotted() function will return True
    when it finds an already installed guest using the same tag.
    Tag-less guests cannot be shared across tests.
    """
    def __init__(self, tag=None, *, name=GUEST_NAME):
        self.log = logging.getLogger(f'{__name__}.{self.__class__.__name__}').debug
        self.tag = tag
        self.name = name
        self.ipaddr = None
        self.ssh_keyfile_path = f'{GUEST_IMG_DIR}/{name}.sshkey'
        self.orig_disk_path = None
        self.orig_disk_format = None
        self.state_file_path = f'{GUEST_IMG_DIR}/{name}.state'
        self.snapshot_path = f'{GUEST_IMG_DIR}/{name}-snap.qcow2'
        # if exists, all snapshot preparation processes were successful
        self.snapshot_ready_path = f'{GUEST_IMG_DIR}/{name}.ready'

    def install(self, location=None, kickstart=None, ks_verbatim=False):
        """
        Install a new guest, to a shut down state.

        If 'location' is given, it is passed to virt-install, otherwise a first
        host repo with an Anaconda stage2 image is used.

        If custom 'kickstart' is used, it is passed to virt-install. It should be
        a Kickstart class instance.

        If 'ks_verbatim' is true, the kickstart is used as-is, otherwise host
        repositories are added to it, and a new ssh keypair is generated, with
        the public key added to the kickstart.
        """
        self.log(f"installing guest {self.name}")

        self._remove_previous(self.name)

        # location (install URL) not given, try using first one found amongst host
        # repository URLs that has Anaconda stage2 image
        if not location:
            for _, url in host_dnf_repos():
                reply = requests.head(url + '/images/install.img')
                if reply.status_code == 200:
                    location = url
                    break
                if versions.rhel <= 7:
                    reply = requests.head(url + '/LiveOS/squashfs.img')
                    if reply.status_code == 200:
                        location = url
                        break
            if not location:
                raise RuntimeError("did not find any install-capable repo amongst host repos")

        if not kickstart:
            kickstart = Kickstart()

        if not ks_verbatim:
            kickstart.add_host_repos()

            ssh_keygen(self.ssh_keyfile_path)
            with open(f'{self.ssh_keyfile_path}.pub') as f:
                pubkey = f.read().rstrip()
            kickstart.add_authorized_key(pubkey)

        disk_path = f'{GUEST_IMG_DIR}/{self.name}.img'
        disk_format = 'raw'

        with kickstart.to_tmpfile() as ksfile:
            virt_install = [
                'pseudotty', 'virt-install',
                # unreleased RHEL tends to have higher-than-released memory use due to
                # the install process not yet being optimized to fit minimum reqs
                '--name', self.name, '--vcpus', '2', '--memory', '3000',
                '--disk', f'path={disk_path},size=20,format={disk_format},cache=unsafe',
                '--network', f'network={NETWORK_NAME}',
                '--location', location,
                '--graphics', 'none', '--console', 'pty', '--rng', '/dev/urandom',
                # this has nothing to do with rhel7, it just tells v-i to use virtio
                # and rhel7 was the first RHEL to do so, so it's the most compatible
                '--initrd-inject', ksfile, '--os-variant', 'rhel7-unknown',
                '--extra-args', f'console=ttyS0 inst.ks=file:/{ksfile.name} inst.notmux inst.noninteractive',  # nopep8
                '--noreboot',
            ]

            executable = util.libdir / 'pseudotty'
            proc = subprocess.Popen(virt_install, stdout=PIPE, executable=executable)
            fail_exprs = [re.compile(x) for x in INSTALL_FAILURES]

            try:
                for line in proc.stdout:
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
                    if any(x.search(line) for x in fail_exprs):
                        proc.terminate()
                        proc.wait()
                        raise RuntimeError(f"installation failed: {util.make_printable(line)}")
                if proc.wait() > 0:
                    raise RuntimeError("virt-install failed")
            except Exception as e:
                self.destroy()
                self.undefine()
                raise e from None

        self.orig_disk_path = disk_path
        self.orig_disk_format = disk_format

    def start(self):
        if guest_domstate(self.name) == 'shut off':
            virsh('start', self.name, check=True)

    def destroy(self):
        if guest_domstate(self.name) == 'running':
            virsh('destroy', self.name, check=True)

    def shutdown(self):
        if guest_domstate(self.name) == 'running':
            virsh('shutdown', self.name, check=True)
        wait_for_domstate(self.name, 'shut off')

    # we cannot shutdown/start a snapshotted guest as that would start it from
    # the persistent non-snapshotted disk - we must somehow reboot the guest OS
    # without exiting the QEMU process - either hard 'reset' or ssh reboot
    def soft_reboot(self):
        """Reboot by issuing 'reboot' via ssh."""
        self.ssh('reboot')  # sudo reboot if unprivileged
        wait_for_ssh(self.ipaddr, to_shutdown=True)
        self.ipaddr = wait_for_ifaddr(self.name)
        wait_for_ssh(self.ipaddr)

    def reset(self):
        virsh('reset', self.name, check=True)

    def undefine(self, incl_storage=False):
        if guest_domstate(self.name):
            storage = ['--remove-all-storage'] if incl_storage else []
            # TODO: add --checkpoints-metadata after we drop RHEL-7
            virsh('undefine', self.name, '--nvram', '--snapshots-metadata',
                  *storage, check=True)

    def can_be_snapshotted(self):
        if not os.path.exists(self.snapshot_ready_path):
            return False
        with open(self.snapshot_ready_path) as f:
            tag = f.read().rstrip()
        return tag == self.tag

    def prepare_for_snapshot(self):
        # do guest first boot, let it settle and finish firstboot tasks,
        # then shut it down + start again, to get the lowest possible page cache
        # (resulting in smallest possible RAM image)
        self.start()
        ip = wait_for_ifaddr(self.name)
        wait_for_ssh(ip)
        self.log("sleeping for 30sec for firstboot to settle")
        time.sleep(30)
        # - disable for now, the ~200M saved RAM is not worth the ~2 minutes
        #self.log(f"waiting for clean shutdown of {self.name}")
        #self.shutdown()  # clean shutdown
        #self.log(f"starting {self.name} back up")
        #self.start()
        #ip = wait_for_ifaddr(self.name)
        #wait_for_ssh(ip)
        #self.log("sleeping for 30sec for second boot to settle, for imaging")
        #time.sleep(30)  # fully finish booting (ssh starts early)

        # save RAM image (domain state)
        virsh('save', self.name, self.state_file_path, check=True)

        # if an external domain is used (not one we installed), read its
        # original disk metadata now
        if not self.orig_disk_path:
            self.orig_disk_path, self.orig_disk_format = get_state_image_disk(self.state_file_path)

        # modify its built-in XML to point to a snapshot-style disk path
        set_state_image_disk(self.state_file_path, self.snapshot_path, 'qcow2')

        if self.tag is not None:
            with open(self.snapshot_ready_path, 'w') as f:
                f.write(self.tag)

    def _restore_snapshotted(self):
        # reused guest from another test, install() or prepare_for_snapshot()
        # were not run for this class instance
        if not self.orig_disk_path:
            ret = virsh('dumpxml', self.name, '--inactive',
                        stdout=PIPE, check=True, universal_newlines=True)
            _, _, _, driver, source = domain_xml_diskinfo(ret.stdout)
            self.orig_disk_format = driver.get('type')
            self.orig_disk_path = source.get('file')

        # running domain left over from a crashed test?
        self.destroy()

        cmd = [
            'qemu-img', 'create', '-f', 'qcow2',
            '-b', self.orig_disk_path, '-F', self.orig_disk_format,
            self.snapshot_path
        ]
        subprocess.run(cmd, check=True)

        virsh('restore', self.state_file_path, check=True)

    def _destroy_snapshotted(self):
        self.destroy()
        os.remove(self.snapshot_path)

    @contextlib.contextmanager
    def snapshotted(self):
        """
        Create a snapshot, restore the guest, ready it for communication.
        """
        if not self.can_be_snapshotted():
            raise RuntimeError(f"guest {self.name} not ready for snapshotting")
        self._restore_snapshotted()
        self.ipaddr = wait_for_ifaddr(self.name)
        wait_for_ssh(self.ipaddr)
        yield self
        self._destroy_snapshotted()

    @contextlib.contextmanager
    def booted(self):
        """
        Just boot the guest, ready it for communication.
        """
        self.start()
        self.ipaddr = wait_for_ifaddr(self.name)
        wait_for_ssh(self.ipaddr)
        yield self

    def _do_ssh(self, *cmd, **run_args):
        ssh_cmdline = [
            'ssh', '-q', '-i', self.ssh_keyfile_path, '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
            f'{GUEST_SSH_USER}@{self.ipaddr}', '--', *cmd
        ]
        self.log(f"running ssh root@{self.ipaddr} {cmd}")
        return subprocess.run(ssh_cmdline, **run_args)

    def ssh(self, *cmd, **kwargs):
        """
        Run a command via ssh(1) inside the guest.

        'kwargs' are passed to subprocess.Popen, except for special 'capture='
        boolean parameter, which is equivalent to stdout=PIPE stderr=PIPE.
        """
        if 'capture' in kwargs and kwargs['capture']:
            kwargs['stdout'] = PIPE
            kwargs['stderr'] = PIPE
            del kwargs['capture']
        return self._do_ssh(*cmd, **kwargs)

    def _do_scp(self, *args):
        scp_cmdline = [
            'scp', '-q', '-i', self.ssh_keyfile_path, '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
            *args
        ]
        return subprocess.run(scp_cmdline, check=True)

    def copy_from(self, remote_file, local_file=None):
        if not local_file:
            local_file = '.'
        self.log(f"copying {remote_file} from guest, to {local_file}")
        self._do_scp(f'{GUEST_SSH_USER}@{self.ipaddr}:{remote_file}', local_file)

    def copy_to(self, local_file, remote_file=None):
        if not remote_file:
            remote_file = '.'
        self.log(f"copying {local_file} to guest, to {remote_file}")
        self._do_scp(local_file, f'{GUEST_SSH_USER}@{self.ipaddr}:{remote_file}')

    @classmethod
    def _remove_previous(cls, name):
        """
        Remove all previous data and metadata for a domain 'name'.

        Useful to clean up an unclean state from a previous use of Guest().
        """
        inst = cls(name)
        inst.destroy()
        inst.undefine(incl_storage=True)
        files = [
            inst.ssh_keyfile_path, f'{inst.ssh_keyfile_path}.pub',
            inst.snapshot_path, inst.state_file_path, inst.snapshot_ready_path
        ]
        for f in files:
            if os.path.exists(f):
                os.remove(f)


#
# guest state checks
#

def guest_domstate(name):
    ret = virsh('domstate', name, stdout=PIPE, stderr=DEVNULL, universal_newlines=True)
    if ret.returncode != 0:  # not defined
        return ''
    return ret.stdout.strip()


def wait_for_domstate(name, state, timeout=300, sleep=0.5):
    """
    Wait until the guest reaches a specified libvirt domain state
    ('running', 'shut off', etc.).
    """
    end_time = datetime.now() + timedelta(seconds=timeout)
    while datetime.now() < end_time:
        if guest_domstate(name) == state:
            return
    raise builtins.TimeoutError(f"wait for {name} to be in {state} timed out")


#
# ssh related helpers, generally used from Guest()
#

def domifaddr(name):
    """
    Return a guest's IP address, queried from libvirt.
    """
    ret = virsh('domifaddr', name, stdout=PIPE, universal_newlines=True, check=True)
    first = ret.stdout.strip().split('\n')[0]  # in case of multiple interfaces
    if not first:
        raise ConnectionError(f"guest {name} has no address assigned yet")
    addr_mask = first.split()[3]
    return addr_mask.split('/')[0]


def wait_for_ifaddr(name, timeout=600, sleep=0.5):
    _log(f"waiting for IP addr of {name} for up to {timeout}sec")
    end_time = datetime.now() + timedelta(seconds=timeout)
    while datetime.now() < end_time:
        try:
            return domifaddr(name)
        except ConnectionError:
            time.sleep(sleep)
    raise builtins.TimeoutError(f"wait for {name} IP addr timed out (not requested DHCP?)")


def wait_for_ssh(ip, port=22, timeout=600, sleep=0.5, to_shutdown=False):
    """
    Attempt to repeatedly connect to a given ip address and port (both strings)
    and return when a connection has been established with a genuine sshd
    service (not just any TCP server).

    If the attempts continue to fail for 'timeout' seconds, raise TimeoutError.

    If 'to_shutdown' is true, wait for ssh to shut down, instead of to start.
    Useful for waiting until a guest reboots without changing domain state.
    """
    state = 'shut down' if to_shutdown else 'start'
    _log(f"waiting for ssh on {ip}:{port} to {state} for up to {timeout}sec")
    end_time = datetime.now() + timedelta(seconds=timeout)
    while datetime.now() < end_time:
        try:
            with socket.create_connection((ip, port), timeout=sleep) as s:
                data = s.recv(10)
                if data.startswith(b'SSH-') and not to_shutdown:
                    return
                # something else on the port? .. just wait + close
                time.sleep(sleep)
        except OSError:
            if to_shutdown:
                return
            time.sleep(sleep)
    raise builtins.TimeoutError(f"ssh wait for {ip}:{port} timed out")


#
# misc helpers
#

def virsh(*virsh_args, **run_args):
    # --quiet just skips the buggy trailing newline
    cmd = ['virsh', '--quiet', *virsh_args]
    return subprocess.run(cmd, **run_args)


# TODO:
# - move to util.
# - resolve metalinks via requests.get() + parse using elementtree XML,
#   look for first <url protocol="http*", as they are sorted by preference already
# - strip the tailing /repodata/repomd.xml
# - cache all results in some global var, so we don't do this repeatedly
def host_dnf_repos():
    """
    Yield tuples of (name,url) of all enabled yum/dnf repositories
    on the host.
    """
    # FIXME: maybe add support for metalink / mirrorlist?
    for repofile in Path('/etc/yum.repos.d').iterdir():
        c = configparser.ConfigParser()
        c.read(repofile)
        for section in c.sections():
            if all(x in c[section] for x in ['name', 'baseurl', 'enabled']):
                if c[section]['enabled'] == '1':
                    yield (section, c[section]['baseurl'])


def ssh_keygen(path):
    """
    Generate private/public keys prefixed by 'path'.
    """
    subprocess.run(['ssh-keygen', '-N', '', '-f', path], stdout=DEVNULL, check=True)


#
# libvirt domain (guest) XML operations
#

def domain_xml_diskinfo(xmlstr):
    domain = ET.fromstring(xmlstr)
    devices = domain.find('devices')
    disk = devices.find('disk')
    driver = disk.find('driver')
    source = disk.find('source')
    if driver is None or source is None:
        raise RuntimeError(f"invalid disk specification")
    return (domain, devices, disk, driver, source)


def get_state_image_disk(image):
    """Get path/format of the first <disk> definition in a RAM image file."""
    ret = virsh('save-image-dumpxml', image, stdout=PIPE, check=True, universal_newlines=True)
    _, _, _, driver, source = domain_xml_diskinfo(ret.stdout)
    image_format = driver.get('type')
    source_file = source.get('file')
    return (source_file, image_format)


def set_state_image_disk(image, source_file, image_format):
    """Set a disk path inside a saved guest RAM image to 'diskpath'."""
    ret = virsh('save-image-dumpxml', image, stdout=PIPE, check=True, universal_newlines=True)
    domain, _, disk, driver, source = domain_xml_diskinfo(ret.stdout)
    driver.set('type', image_format)
    source.set('file', source_file)
    # saved state images have empty <backingStore/> for some weird reason,
    # breaking our snapshotting hack -- just remove it
    backing_store = disk.find('backingStore')
    if backing_store is not None:
        disk.remove(backing_store)
    # RHEL-7 doesn't leave enough space in the RAM image for the extra few
    # bytes added by a slightly longer disk path - free up this space by
    # deleting a useless <pm> section
    pm = domain.find('pm')
    if pm is not None:
        domain.remove(pm)
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.xml') as f:
        f.write(ET.tostring(domain))
        f.flush()
        virsh('save-image-define', image, f.name, check=True)

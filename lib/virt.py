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

Example using snapshots:

    import virt

    virt.Host.setup()
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

    virt.Host.setup()
    g = virt.Guest()

    ks = virt.Kickstart()
    ks.add_post('some test-specific stuff')
    g.install(kickstart=ks)

    with g.booted():
        g.ssh( ... )
        g.ssh( ... )
"""

import os
import sys
import re
import socket
import time
import subprocess
import textwrap
import contextlib
import tempfile
import json
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

from . import util, versions, dnf

GUEST_NAME = 'contest'
GUEST_LOGIN_PASS = 'contest'
GUEST_SSH_USER = 'root'

GUEST_IMG_DIR = '/var/lib/libvirt/images'

NETWORK_NETMASK = '255.255.252.0'
NETWORK_HOST = '192.168.120.1'
# 1000 guest addrs, refreshing after a week, should be enough
NETWORK_RANGE = ['192.168.120.2', '192.168.123.254']
NETWORK_EXPIRY = 168

# as byte-strings
INSTALL_FAILURES = [
    br"org\.fedoraproject\.Anaconda\.Addons\.OSCAP\.*: The installation should be aborted",
    br"The installation should be aborted.",
    br"\.common\.OSCAPaddonError:",
    br"The installation was stopped due to an error",
    br"There was an error running the kickstart script",
    br"Aborting the installation",
    br"Something went wrong during the final hardening",
    # RHEL-7 ignores inst.noninteractive
    br"Please respond ",
]

PIPE = subprocess.PIPE
DEVNULL = subprocess.DEVNULL


class Host:
    """
    Utilities for host system preparation.
    """
    @staticmethod
    def check_virt_capability():
        """
        Return True if the host has HW-accelerated virtualization support (HVM).
        Else return False.
        """
        with open('/proc/cpuinfo') as f:
            cpuinfo = f.read()
        for virt_type in ['vmx', 'svm']:
            if re.search(fr'\nflags\t+:.* {virt_type}( |$)', cpuinfo):
                return True
        return False

    @staticmethod
    def setup_network():
        net_name = 'default'

        # unfortunately, there's no easy way to tell if we have changed the
        # libvirt-included default network - libvirt seems to silently erase both
        # <title> and <description> and dump-xml ignores <metadata> too,
        # so just rely on ip address ranges - in the case of a rare false positive
        # match, we'll just re-define the network, no big deal
        def is_our_network(xml):
            return re.search(
                f'''<range start='{NETWORK_RANGE[0]}' end='{NETWORK_RANGE[1]}'>''',
                xml,
            )

        def define_our_network():
            util.log(f"defining libvirt network: {net_name}")
            net_xml = util.dedent(fr'''
                <network>
                  <name>{net_name}</name>
                  <forward mode='nat'/>
                  <bridge stp='off' delay='0'/>
                  <ip address='{NETWORK_HOST}' netmask='{NETWORK_NETMASK}'>
                    <dhcp>
                      <range start='{NETWORK_RANGE[0]}' end='{NETWORK_RANGE[1]}'>
                        <lease expiry='{NETWORK_EXPIRY}' unit='hours'/>
                      </range>
                    </dhcp>
                  </ip>
                </network>
            ''')
            with tempfile.NamedTemporaryFile(mode='w', suffix='.xml') as f:
                f.write(net_xml)
                f.flush()
                virsh('net-define', f.name, check=True)
            virsh('net-autostart', net_name, check=True)
            virsh('net-start', net_name, check=True)

        info = virsh('net-info', net_name, stdout=PIPE, stderr=DEVNULL, universal_newlines=True)
        # if default already exists
        if info.returncode == 0:
            dumpxml = virsh('net-dumpxml', net_name, stdout=PIPE, universal_newlines=True)
            if not is_our_network(dumpxml.stdout):
                if re.search(r'\nActive: +yes\n', info.stdout):
                    virsh('net-destroy', net_name, check=True)
                virsh('net-undefine', net_name, check=True)
                define_our_network()
        else:
            define_our_network()

    @classmethod
    def setup(self):
        if not self.check_virt_capability():
            raise RuntimeError("host has no HVM virtualization support")

        ret = subprocess.run(['systemctl', 'is-active', '--quiet', 'libvirtd'])
        if ret.returncode != 0:
            util.subprocess_run(['systemctl', 'start', 'libvirtd'], check=True)

        self.setup_network()


#
# Anaconda Kickstart related customizations
#

class Kickstart:
    PARTITIONS = [
        ('/boot', 700),
        ('/', 1000),
        ('/home', 100),
        ('/var', 6000),
        ('/var/log', 1000),
        ('/var/log/audit', 1000),
        ('/var/tmp', 1000),
        ('/srv', 100),
        ('/opt', 100),
        ('/tmp', 1000),
        ('/usr', 8000),
    ]

    TEMPLATE = util.dedent(fr'''
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
    ''')

    PACKAGES = [
        'openscap-scanner',
    ]

    def __init__(self, template=TEMPLATE, packages=PACKAGES, partitions=PARTITIONS):
        self.ks = template
        self.appends = []
        self.packages = packages
        self.partitions = partitions

    def _assemble_ks(self):
        partitions_block = '\n'.join(
            (f'part {mountpoint} --size={size}' for mountpoint, size in self.partitions),
        )
        appends_block = '\n'.join(self.appends)
        packages_block = '\n'.join(self.packages)
        packages_block = f'%packages\n{packages_block}\n%end'
        return '\n\n'.join([self.ks, partitions_block, appends_block, packages_block])
        # self.ks + self.packages + self.scripts

    @contextlib.contextmanager
    def to_tmpfile(self):
        final_ks = self._assemble_ks()
        util.log(f"writing:\n{textwrap.indent(final_ks, '    ')}")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ks.cfg') as f:
            f.write(final_ks)
            f.flush()
            yield Path(f.name)
            # backing file of f is deleted when we exit this scope

    def append(self, content):
        """Append arbitrary string content to the kickstart template."""
        self.appends.append(content)

    def add_post(self, content):
        new = ('%post --interpreter=/bin/bash --erroronfail\n'
               'set -xe; exec >/dev/tty 2>&1\n' + content + '\n%end')
        self.append(new)

    def add_packages(self, pkgs):
        self.packages += pkgs

    def add_package_group(self, group):
        if versions.rhel < 8:
            self.packages.append(f'@^{group}')
        else:
            self.packages.append(f'@{group}')

    def add_install_only_repo(self, name, baseurl):
        self.appends.append(f'repo --name={name} --baseurl={baseurl}')

    def add_host_repos(self):
        installed_repos = []
        for reponame, config in dnf.repo_configs():
            # TODO: repo --metalink support, don't assume baseurl exists
            baseurl = config['baseurl']
            self.appends.append(f'repo --name={reponame} --baseurl={baseurl}')
            installed_repos.append(
                f'cat > /etc/yum.repos.d/{reponame}.repo <<\'EOF\'\n' +
                f'[{reponame}]\n' +
                '\n'.join(f'{k}={v}' for k, v in config.items()) +
                '\nEOF')
        self.add_post('\n'.join(installed_repos))

    def add_oscap(self, keyvals):
        """Append an OSCAP addon section, with key=value pairs from 'keyvals'."""
        lines = '\n'.join(f'  {k} = {v}' for k, v in keyvals.items())
        section = 'org_fedora_oscap' if versions.rhel < 9 else 'com_redhat_oscap'
        self.append(f'%addon {section}\n{lines}\n%end')

    def add_authorized_key(self, pubkey, homedir='/root', owner='root'):
        script = util.dedent(fr'''
            mkdir -m 0700 -p {homedir}/.ssh
            cat >> {homedir}/.ssh/authorized_keys <<EOF
            {pubkey}
            EOF
            chmod 0600 {homedir}/.ssh/authorized_keys
            chown {owner} -R {homedir}/.ssh
        ''')
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

    # custom post-install setup to allow smooth login and qemu-qa command execution
    SETUP = util.dedent(r'''
        # hack sshd cmdline to allow root login,
        # also hack UseDNS on RHEL-7, otherwise login takes ~30sec
        echo "OPTIONS=-oPermitRootLogin=yes -oUseDNS=no" >> /etc/sysconfig/sshd
        # allow qemu-guest-agent to execute code
        sed '/^BLACKLIST_RPC=/s/=.*/=/'   -i /etc/sysconfig/qemu-ga  # RHEL-7/8
        sed '/^BLOCK_RPCS=/s/=.*/=/'      -i /etc/sysconfig/qemu-ga  # RHEL-9+
        sed '/^FILTER_RPC_ARGS=/s/=.*/=/' -i /etc/sysconfig/qemu-ga  # RHEL-9.4+
        semanage permissive -a virt_qemu_ga_t
    ''')
    SETUP_REQUIRES = (
        ['openssh-server', 'qemu-guest-agent']
        # because of semanage in SETUP
        + (['policycoreutils-python'] if versions.rhel < 8 else ['policycoreutils-python-utils'])
    )

    def __init__(self, tag=None, *, name=GUEST_NAME):
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
        util.log(f"installing guest {self.name}")

        # remove any previously installed guest
        self.wipe()

        # location (install URL) not given, try using first one found amongst host
        # repository URLs that has Anaconda stage2 image
        if not location:
            location = dnf.installable_url()

        if not kickstart:
            kickstart = Kickstart()

        http_port = 8090

        if not ks_verbatim:
            kickstart.add_host_repos()
            util.ssh_keygen(self.ssh_keyfile_path)
            with open(f'{self.ssh_keyfile_path}.pub') as f:
                pubkey = f.read().rstrip()
            kickstart.add_authorized_key(pubkey)
            kickstart.add_install_only_repo(
                'contest-rpmpack',
                f'http://{NETWORK_HOST}:{http_port}/repo',
            )
            kickstart.add_packages([util.RPMPACK_NAME])

        disk_path = f'{GUEST_IMG_DIR}/{self.name}.img'
        disk_format = 'raw'
        cpus = os.cpu_count() or 1

        with contextlib.ExitStack() as stack:
            # create a custom RPM to run guest setup scripts via RPM scriptlets
            # and install it during Anaconda installation
            pack = util.RpmPack()
            pack.post.append(self.SETUP)
            pack.requires += self.SETUP_REQUIRES
            repo = stack.enter_context(pack.build_as_repo())

            # host the custom RPM on a HTTP server, as Anaconda needs a YUM repo
            # to pull packages from
            srv = util.BackgroundHTTPServer(NETWORK_HOST, http_port)
            srv.add_dir(repo, 'repo')
            stack.enter_context(srv)

            ksfile = stack.enter_context(kickstart.to_tmpfile())

            virt_install = [
                'pseudotty', 'virt-install',
                # installing from HTTP URL leads to Anaconda downloading stage2
                # to RAM, leading to notably higher memory requirements during
                # installation - we reduce it down to 2000M after install
                '--name', self.name, '--vcpus', str(cpus), '--memory', '3000',
                '--disk', f'path={disk_path},size=20,format={disk_format},cache=unsafe',
                '--network', 'network=default', '--location', location,
                '--graphics', 'none', '--console', 'pty', '--rng', '/dev/urandom',
                # this has nothing to do with rhel7, it just tells v-i to use virtio
                # and rhel7 was the first RHEL to do so, so it's the most compatible
                '--initrd-inject', ksfile, '--os-variant', 'rhel7-unknown',
                '--extra-args', f'console=ttyS0 inst.ks=file:/{ksfile.name} '
                                'systemd.journald.forward_to_console=1 '
                                'inst.notmux inst.noninteractive inst.noverifyssl inst.sshd',
                '--noreboot',
            ]

            util.log(f"calling {virt_install}")
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

        # installed system doesn't need as much RAM, alleviate swap pressure
        set_domain_memory(self.name, 2000)

        self.orig_disk_path = disk_path
        self.orig_disk_format = disk_format

    def start(self):
        if guest_domstate(self.name) == 'shut off':
            virsh('start', self.name, check=True)

    def destroy(self):
        state = guest_domstate(self.name)
        if state and state != 'shut off':
            virsh('destroy', self.name, check=True)

    def shutdown(self):
        if guest_domstate(self.name) == 'running':
            virsh('shutdown', self.name, check=True)
        wait_for_domstate(self.name, 'shut off')

    # we cannot shutdown/start a snapshotted guest as that would start it from
    # the persistent non-snapshotted disk - we must somehow reboot the guest OS
    # without exiting the QEMU process - hard 'reset' or ssh/qemu-ga reboot
    def soft_reboot(self, fix_login=True):
        """Reboot by issuing 'reboot' via ssh."""
        if fix_login:
            self.guest_agent_exec('/sbin/setenforce', '0', check=True)
            self.guest_agent_exec('/bin/chage', '-d', '99999', 'root', check=True)
        util.log("rebooting using qemu-guest-agent")
        self.guest_agent_cmd('guest-shutdown', {'mode': 'reboot'}, blind=True)
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
        util.log("sleeping for 30sec for firstboot to settle")
        time.sleep(30)
        # - disable for now, the ~200M saved RAM is not worth the ~2 minutes
        #util.log(f"waiting for clean shutdown of {self.name}")
        #self.shutdown()  # clean shutdown
        #util.log(f"starting {self.name} back up")
        #self.start()
        #ip = wait_for_ifaddr(self.name)
        #wait_for_ssh(ip)
        #util.log("sleeping for 30sec for second boot to settle, for imaging")
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

        # running domain left over from a crashed test,
        # or by CONTEST_LEAVE_GUEST_RUNNING
        self._destroy_snapshotted()

        cmd = [
            'qemu-img', 'create', '-f', 'qcow2',
            '-b', self.orig_disk_path, '-F', self.orig_disk_format,
            self.snapshot_path
        ]
        util.subprocess_run(cmd, check=True)

        virsh('restore', self.state_file_path, check=True)

    def _destroy_snapshotted(self):
        self.destroy()
        if os.path.exists(self.snapshot_path):
            os.remove(self.snapshot_path)

    def _log_leave_running_notice(self):
        out = textwrap.dedent(f"""\n
            Leaving guest running, the test might break!
            To ssh into it, log in (ssh) into the VM host first, then do:
                ssh -i {self.ssh_keyfile_path} root@{self.ipaddr}
            """)
        util.log(textwrap.indent(out, '    '), skip_frames=1)

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
        util.log(f"guest {self.name} ready")
        try:
            yield self
        finally:
            if os.environ.get('CONTEST_LEAVE_GUEST_RUNNING') == '1':
                self._log_leave_running_notice()
            else:
                self._destroy_snapshotted()

    @contextlib.contextmanager
    def booted(self):
        """
        Just boot the guest, ready it for communication.
        """
        self.start()
        self.ipaddr = wait_for_ifaddr(self.name)
        wait_for_ssh(self.ipaddr)
        util.log(f"guest {self.name} ready")
        try:
            yield self
        finally:
            if os.environ.get('CONTEST_LEAVE_GUEST_RUNNING') == '1':
                self._log_leave_running_notice()
            else:
                try:
                    util.log(f"shutting down {self.name}")
                    self.shutdown()
                except TimeoutError:
                    util.log(f"shutdown timed out, destroying {self.name}")
                    self.destroy()

    def _do_ssh(self, *cmd, func=util.subprocess_run, capture=False, **run_args):
        if capture:
            run_args['stdout'] = PIPE
            run_args['stderr'] = PIPE
        ssh_cmdline = [
            'ssh', '-q', '-i', self.ssh_keyfile_path, '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
            f'{GUEST_SSH_USER}@{self.ipaddr}', '--', *cmd
        ]
        return func(ssh_cmdline, **run_args)

    def ssh(self, *cmd, **kwargs):
        """Run a command via ssh(1) inside the guest."""
        return self._do_ssh(*cmd, **kwargs)

    def ssh_stream(self, *cmd, **kwargs):
        return self._do_ssh(*cmd, func=util.subprocess_stream, **kwargs)

    def _do_scp(self, *args):
        scp_cmdline = [
            'scp', '-q', '-i', self.ssh_keyfile_path, '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
            *args
        ]
        return util.subprocess_run(scp_cmdline, check=True)

    def copy_from(self, remote_file, local_file=None):
        if not local_file:
            local_file = '.'
        util.log(f"copying {remote_file} from guest, to {local_file}")
        self._do_scp(f'{GUEST_SSH_USER}@{self.ipaddr}:{remote_file}', local_file)

    def copy_to(self, local_file, remote_file=None):
        if not remote_file:
            remote_file = '.'
        util.log(f"copying {local_file} to guest, to {remote_file}")
        self._do_scp(local_file, f'{GUEST_SSH_USER}@{self.ipaddr}:{remote_file}')

    def guest_agent_cmd(self, cmd, args=None, blind=False):
        """
        Execute an arbitrary qemu-guest-agent command.

        If 'blind' is specified, the command is executed without waiting for
        completion and nothing is returned.
        """
        request = {'execute': cmd}
        if args:
            request['arguments'] = args
        ret = virsh('qemu-agent-command', self.name, json.dumps(request), check=not blind,
                    universal_newlines=True, stdout=PIPE, stderr=DEVNULL if blind else None)
        if blind:
            return
        return json.loads(ret.stdout)['return']

    def guest_agent_exec(self, *args, capture=False, check=False, **kwargs):
        """
        Execute a remote command using qemu-guest-agent running on the guest.

        The first argument must be a full absolute path to the executable.

        A subprocess.CompletedProcess instance is returned with returncode and
        optionally stdout/stderr if 'capture' is True.
        """
        request = {
            'path': args[0],
            'arg': args[1:],
            'capture-output': capture,
        }
        util.log(f"sending {request}")
        ret = self.guest_agent_cmd('guest-exec', request, **kwargs)
        pid = ret['pid']

        while True:
            ret_json = self.guest_agent_cmd('guest-exec-status', {'pid': pid})
            if ret_json['exited']:
                break
            time.sleep(0.1)

        completed = subprocess.CompletedProcess(args, -1)

        # qemu-ga splits exit into into 'exitcode' and 'signal',
        # translate it back to emulate a shell-style exitcode
        if 'signal' in ret_json:
            completed.returncode = ret_json['signal'] + 128
        else:
            completed.returncode = ret_json['exitcode']

        if capture:
            # if the command returns empty output, qemu-ga will omit the key!
            if 'out-data' in ret_json:
                completed.stdout = base64.b64decode(ret_json['out-data'])
            if 'err-data' in ret_json:
                completed.stderr = base64.b64decode(ret_json['err-data'])

        util.log(f"ended with {completed}")
        if check:
            completed.check_returncode()
        return completed

    def wipe(self):
        """
        Remove all previous data and metadata of a domain.

        Useful to clean up an unclean state from a previous use of Guest(),
        or just to remove any leftovers after using a one-time guest.
        """
        self.destroy()
        self.undefine(incl_storage=True)
        files = [
            self.ssh_keyfile_path, f'{self.ssh_keyfile_path}.pub',
            self.snapshot_path, self.state_file_path, self.snapshot_ready_path,
        ]
        for f in files:
            if os.path.exists(f):
                os.remove(f)
        # RHEL-7 specific, see domifaddr()
        ipaddr = Path(GUEST_IMG_DIR) / f'{self.name}.ipaddr'
        if ipaddr.exists():
            ipaddr.unlink()


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
    util.log(f"waiting for {name} to be {state} for {timeout}sec")
    end_time = datetime.now() + timedelta(seconds=timeout)
    while datetime.now() < end_time:
        if guest_domstate(name) == state:
            return
    raise TimeoutError(f"wait for {name} to be in {state} timed out")


#
# ssh related helpers, generally used from Guest()
#

# TODO: RHEL-7 libvirt has no <lease ..> tag, so it expires the address within
#       1h, making restored snapshot fail to find the address via domifaddr -
#       work around this by storing the IP address separately - this is not
#       perfect (may conflict), but GEFN for 1-guest-at-a-time
def domifaddr(name):
    """
    Return a guest's IP address, queried from libvirt.
    """
    if versions.rhel < 8:
        cache = Path(GUEST_IMG_DIR) / f'{name}.ipaddr'
        if cache.exists():
            return cache.read_text()
    ret = virsh('domifaddr', name, stdout=PIPE, universal_newlines=True, check=True)
    first = ret.stdout.strip().split('\n')[0]  # in case of multiple interfaces
    if not first:
        raise ConnectionError(f"guest {name} has no address assigned yet")
    addr_mask = first.split()[3]
    addr = addr_mask.split('/')[0]
    if versions.rhel < 8:
        cache.write_text(addr)
    return addr


def wait_for_ifaddr(name, timeout=600, sleep=0.5):
    util.log(f"waiting for IP addr of {name} for up to {timeout}sec")
    end_time = datetime.now() + timedelta(seconds=timeout)
    while datetime.now() < end_time:
        try:
            return domifaddr(name)
        except ConnectionError:
            time.sleep(sleep)
    raise TimeoutError(f"wait for {name} IP addr timed out (not requested DHCP?)")


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
    util.log(f"waiting for ssh on {ip}:{port} to {state} for up to {timeout}sec")
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
    raise TimeoutError(f"ssh wait for {ip}:{port} timed out")


#
# misc helpers
#

def virsh(*virsh_args, **run_args):
    # --quiet just skips the buggy trailing newline
    cmd = ['virsh', '--quiet', *virsh_args]
    return subprocess.run(cmd, **run_args)


def translate_ssg_kickstart(profile):
    """
    Parse (and tweak) a kickstart shipped with the upstream content
    into class Kickstart instance.
    """
    ks_text = ''
    ks_file = util.get_kickstart(profile)
    util.log(f"using orig file: {ks_file}")

    with open(ks_file) as f:
        for line in f:
            line = line.rstrip('\n')

            # use our own password
            if re.match('^rootpw ', line):
                line = f'rootpw {GUEST_LOGIN_PASS}'

            # don't hardcode interface name because we use network installs,
            # which fill in the booted-from device automatically
            elif re.match('^network ', line):
                line = re.sub(' --device[= ][^ ]+', '', line)

            # STIG uses 10 GB audit because of DISA requiring large partitions,
            # checked by 'auditd_audispd_configure_sufficiently_large_partition'
            # (see https://github.com/ComplianceAsCode/content/pull/7141)
            # - reducing this to 512 makes the rest of the partitions align
            #   perfectly at 20448 MB, same as other kickstarts
            elif re.match('^logvol /var/log/audit .*--size=10240', line):
                line = re.sub('--size=[^ ]+', '--size=512', line)

            ks_text += f'{line}\n'

    # remove %addon oscap, we'll add our own
    ks_text = re.sub(r'\n%addon .+?_oscap\n.+?\n%end[^\n]*', '', ks_text, flags=re.DOTALL)

    # leave original %packages - Anaconda can handle multiple %packages sections
    # just fine (when we later add ours during installation),
    # however clear out partitions as content-provided kickstarts have their own
    return Kickstart(template=ks_text, partitions=[])


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
        raise RuntimeError("invalid disk specification")
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


def set_domain_memory(domain, amount, unit='MiB'):
    """Set the amount of RAM allowed for a defined guest."""
    ret = virsh('dumpxml', domain, stdout=PIPE, check=True, universal_newlines=True)
    domain = ET.fromstring(ret.stdout)
    for name in ['memory', 'currentMemory']:
        mem = domain.find(name)
        mem.set('unit', unit)
        mem.text = str(amount)
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.xml') as f:
        f.write(ET.tostring(domain))
        f.flush()
        virsh('define', f.name, check=True)

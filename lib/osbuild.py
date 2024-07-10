"""
Provides utilities for creating, importing and using Image Builder made images
for virtual machines, and a context manager to use them as VMs.

The classes and methods are derived from lib.virt, but instead of installing
VMs via Guest.install(), they are created from images via Guest.create().

    import osbuild

    osbuild.Host.setup()
    g = osbuild.Guest()
    profile = 'stig'

    # optional
    blueprint = osbuild.Blueprint(profile)
    blueprint.add_something( ... )

    g.create(profile=profile, blueprint=blueprint)

    with g.booted():
        g.ssh( ... )
        g.ssh( ... )

Snapshotting is currently not supported/tested with this approach.
"""

import os
import sys
import re
import subprocess
import textwrap
import contextlib
import tempfile
import json
import platform
import shutil
import time
import collections
from pathlib import Path

from lib import util, dnf, virt
from conf import remediation


class Host:
    @staticmethod
    def setup():
        virt.Host.setup()
        for unit in ['osbuild-composer.socket', 'osbuild-local-worker.socket']:
            ret = subprocess.run(['systemctl', 'is-active', '--quiet', unit])
            if ret.returncode != 0:
                util.subprocess_run(['systemctl', 'start', unit], check=True)


class ComposerRepos:
    """
    These are so-called "system" repositories recognized by osbuild-composer,
    not Blueprint customizations.

    Note that these are not equivalent to 'composer-cli sources' - the docs
    make it seem like so, but osbuild developers confirmed that only the .json
    repos are used for the build process.
    """

    ETC_REPOS = Path('/etc/osbuild-composer/repositories')
    USR_REPOS = Path('/usr/share/osbuild-composer/repositories')

    def __init__(self):
        self.repos = []

    def add_host_repos(self):
        for reponame, config in dnf.repo_configs():
            new = {
                'name': reponame,
                'check_gpg': False,
            }
            for key in ['baseurl', 'metalink']:
                if key in config:
                    new[key] = config[key]
            self.repos.append(new)

    def assemble(self):
        # wrap it in a per-arch dict key
        return json.dumps({platform.machine(): self.repos}, indent=4)

    @contextlib.contextmanager
    def to_composer(self):
        # unfortunately, osbuild-composer has many default .json repositories
        # pointing to CDN, and selects which to use based on OS major/minor
        # version, so we work around this by overriding all possible .json
        # filenames in /etc with our content (symlinks don't work)
        repos = self.assemble()
        util.log(f"using composer repos:\n{textwrap.indent(repos, '    ')}")
        if self.ETC_REPOS.exists():
            shutil.rmtree(self.ETC_REPOS)
        self.ETC_REPOS.mkdir(parents=True)
        for repofile in self.USR_REPOS.iterdir():
            (self.ETC_REPOS / repofile.name).write_text(repos)
        util.subprocess_run(['systemctl', 'restart', 'osbuild-composer.service'], check=True)
        yield
        shutil.rmtree(self.ETC_REPOS)
        util.subprocess_run(['systemctl', 'restart', 'osbuild-composer.service'], check=True)


class Compose:
    _Entry = collections.namedtuple(
        'ComposeEntry',
        ['id', 'status', 'blueprint', 'version', 'type'],
    )
    RUNNING_STATUSES = ['WAITING', 'RUNNING']
    FINISHED_STATUSES = ['FINISHED', 'FAILED']

    @classmethod
    def _get_status(self, filter):
        out = composer_cli_out('compose', 'list', log=False)
        lines = iter(out.strip('\n').split('\n'))
        next(lines)  # skip header (first line)
        for line in lines:
            entry = self._Entry(*re.split(r'[ \t]+', line))
            if filter(entry):
                return entry
        return None

    @classmethod
    def _wait_for_finished(self, blueprint_name, sleep=1):
        entry = self._get_status(lambda x: x.blueprint == blueprint_name)
        if not entry:
            raise FileNotFoundError(f"compose for {blueprint_name} not found in list")
        util.log(f"waiting for compose {entry.id} to be built")
        new = entry
        while new.status not in self.FINISHED_STATUSES:
            new = self._get_status(lambda x: x.id == entry.id)
            if not new:
                raise FileNotFoundError(f"compose {entry.id} disappeared")
            time.sleep(sleep)
        return new

    @classmethod
    @contextlib.contextmanager
    def build(self, blueprint_name):
        entry = self._get_status(lambda x: x.blueprint == blueprint_name)
        # delete any existing compose
        if entry:
            if entry.status in self.RUNNING_STATUSES:
                composer_cli('compose', 'cancel', entry.id)
            composer_cli('compose', 'delete', entry.id)
        # start and wait
        composer_cli('compose', 'start', blueprint_name, 'qcow2')
        entry = self._wait_for_finished(blueprint_name)
        # check & yield
        if entry.status != 'FINISHED':
            composer_cli('compose', 'log', entry.id)
            raise RuntimeError(f"failed to build: {entry}")
        yield entry.id
        # clean up
        composer_cli('compose', 'delete', entry.id)


# this is using a different approach to class Kickstart or class RpmPack
# because of varying data types key/values of tables/arrays can have,
# ie. transforming python dict to
#   [customizations.openscap.tailoring]
#   unselected = [ "grub2_password" ]
# would require logic for quoting str(), for transforming arrays into [ ], etc.,
# so let's just append strings instead
class Blueprint:
    NAME = 'contest_blueprint'
    HEADER = util.dedent(fr'''
        name = "{NAME}"
        description = "Testing blueprint created by the Contest test suite"
        version = "1.0.0"
    ''')

    def __init__(self, profile=None):
        if profile:
            self.assembled = (
                self.from_oscap(profile)
                + '\n# ---------- oscap blueprint ends here ----------\n'
            )
            util.log(f"generated blueprint from oscap:\n{textwrap.indent(self.assembled, '    ')}")
        else:
            self.assembled = f'{self.HEADER}\n\n'

    def from_oscap(self, profile):
        cmd = [
            'oscap', 'xccdf', 'generate', '--profile', profile,
            'fix', '--fix-type', 'blueprint',
            util.get_datastream(),
        ]
        ret = util.subprocess_run(cmd, check=True, universal_newlines=True, stdout=subprocess.PIPE)
        # replace blueprint name, it's an unique identifier for composer-cli,
        # however replace only the first occurence of 'name', as later sections
        # like [[packages]] would also match ^name=...
        return re.sub('^name = .*', f'name = "{self.NAME}"', ret.stdout, count=1, flags=re.M)

    def add_user(self, name, *, password=None, groups=None, ssh_pubkey=None):
        self.assembled += '[[customizations.user]]\n'
        self.assembled += f'name = "{name}"\n'
        if password:
            self.assembled += f'password = "{password}"\n'
        if groups:
            groups_str = ','.join(f'"{x}"' for x in groups)
            self.assembled += f'groups = [ {groups_str} ]\n'
        if ssh_pubkey:
            self.assembled += f'key = "{ssh_pubkey}"\n'

    def add_package(self, name):
        self.assembled += util.dedent(fr'''
            [[packages]]
            name = "{name}"
        ''') + '\n'

    def add_package_group(self, name):
        self.assembled += util.dedent(fr'''
            [[groups]]
            name = "{name}"
        ''') + '\n'

    def add_partition(self, mountpoint, minsize):
        self.assembled += util.dedent(fr'''
            [[customizations.filesystem]]
            mountpoint = "{mountpoint}"
            minsize = {minsize}
        ''') + '\n'

    def set_openscap_datastream(self, ds_file):
        pre, header, post = self.assembled.partition('\n[customizations.openscap]\n')
        if not header:
            raise SyntaxError("openscap section not found")
        self.assembled = '\n'.join([
            pre,
            header.strip('\n'),
            f'datastream = "{ds_file}"',
            post,
        ])

    def add_openscap_tailoring(self, *, selected=None, unselected=None):
        if '[customizations.openscap.tailoring]' in self.assembled:
            raise SyntaxError("openscap.taioring section already exists")
        if not selected and not unselected:
            return
        self.assembled += '[customizations.openscap.tailoring]\n'
        for name, vals in [('selected', selected), ('unselected', unselected)]:
            if vals:
                strings = ','.join(f'"{x}"' for x in vals)
                self.assembled += f'{name} = [ {strings} ]\n'

    @contextlib.contextmanager
    def to_tmpfile(self):
        bp = self.assembled
        util.log(f"using blueprint:\n{textwrap.indent(bp, '    ')}")
        with tempfile.NamedTemporaryFile(mode='w') as f:
            f.write(bp)
            f.flush()
            yield Path(f.name)

    @contextlib.contextmanager
    def to_composer(self):
        blueprints = composer_cli_out('blueprints', 'list', log=False)
        if self.NAME in blueprints:
            composer_cli('blueprints', 'delete', self.NAME)
        with self.to_tmpfile() as f:
            composer_cli('blueprints', 'push', f)
        yield self.NAME
        composer_cli('blueprints', 'delete', self.NAME)


class Guest(virt.Guest):
    DATASTREAM = '/root/contest-ds.xml'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.osbuild_log = f'{virt.GUEST_IMG_DIR}/{self.name}-osbuild.txt'

    def wipe(self):
        super().wipe()
        log = Path(self.osbuild_log)
        if log.exists():
            os.remove(log)

    def install(*args, **kwargs):
        raise NotImplementedError("install() is not supported, use create()")

    def create(self, *, blueprint=None, bp_verbatim=None, profile=None):
        """
        Create a guest disk image via osbuild, and import it as a new guest
        domain into libvirt.

        If 'blueprint' is given as a 'class Blueprint' instance, it is used
        for further customizations instead of a fresh Blueprint instance.

        'bp_verbatim' further prevents these customizations, using the
        blueprint as-provided by test code.

        If 'profile' is specified, the created image will be hardened using
        openscap via the specified profile.
        """
        util.log(f"creating guest {self.name}")

        # remove any previously installed guest
        self.wipe()

        if not blueprint:
            blueprint = Blueprint(profile)

        if not bp_verbatim:
            # copy our default package list from virt.Kickstart
            for pkg in virt.Kickstart.PACKAGES:
                blueprint.add_package(pkg)
            # generate the ssh key on the same place as virt.Guest
            util.ssh_keygen(self.ssh_keyfile_path)
            with open(f'{self.ssh_keyfile_path}.pub') as f:
                pubkey = f.read().rstrip()
            blueprint.add_user('root', password=virt.GUEST_LOGIN_PASS, ssh_pubkey=pubkey)
            # add openscap hardening, honor global excludes
            if profile:
                blueprint.set_openscap_datastream(self.DATASTREAM)
                blueprint.add_openscap_tailoring(unselected=remediation.excludes())

        disk_path = Path(f'{virt.GUEST_IMG_DIR}/{self.name}.img')

        with contextlib.ExitStack() as stack:
            # osbuild doesn't support running Anaconda %post-style custom
            # scripts, the only way to run additional shell code is via
            # RPM scriptlets, so add custom guest setup via RpmPack
            pack = util.RpmPack()
            pack.add_host_repos()
            # inherited from virt.Guest
            pack.post.append(self.SETUP)
            pack.requires += self.SETUP_REQUIRES
            pack.add_file(util.get_datastream(), self.DATASTREAM)
            repo = stack.enter_context(pack.build_as_repo())
            # ensure the custom RPM is added during image building
            blueprint.add_package(util.RpmPack.NAME)

            # osbuild-composer doesn't support file:// repos, so host
            # the custom RPM on a HTTP server
            srv = util.BackgroundHTTPServer('127.0.0.1', 0)
            srv.add_dir(repo, 'repo')
            stack.enter_context(srv)

            # overwrite default Red Hat CDN host repos via a custom HTTP server
            repos = ComposerRepos()
            repos.add_host_repos()
            http_host, http_port = srv.server.server_address
            repos.repos.append({
                'name': 'contest-rpmpack',
                'baseurl': f'http://{http_host}:{http_port}/repo',
            })
            stack.enter_context(repos.to_composer())

            bp_name = stack.enter_context(blueprint.to_composer())

            # re-try multiple times to try to avoid a bug:
            # ERROR: Depsolve Error: Get "http://localhost/.../depsolve/contest_blueprint": EOF
            for _ in range(5):
                ret = composer_cli(
                    'blueprints', 'depsolve', bp_name, check=False, universal_newlines=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
                sys.stdout.write(ret.stdout)
                if ret.returncode == 0:
                    break
                elif re.match('ERROR: Depsolve Error: Get "[^"]+": EOF\n', ret.stdout):
                    continue
                else:
                    raise RuntimeError("depsolve returned unknown error")
            else:
                raise RuntimeError("depsolve failed, retries depleted")

            ident = stack.enter_context(Compose.build(bp_name))

            if disk_path.exists():
                os.remove(disk_path)
            composer_cli('compose', 'image', ident, '--filename', disk_path)

            # get image building log, try to limit its size by cutting off
            # everything before openscap
            log = composer_cli_out('compose', 'log', ident)
            idx = log.find('Stage: org.osbuild.oscap')
            if idx != -1:
                log = log[idx:]
            Path(self.osbuild_log).write_text(log)

        cpus = os.cpu_count() or 1

        virt_install = [
            'pseudotty', 'virt-install',
            # installing from HTTP URL leads to Anaconda downloading stage2
            # to RAM, leading to notably higher memory requirements during
            # installation - we reduce it down to 2000M after install
            '--name', self.name, '--vcpus', str(cpus), '--memory', '2000',
            '--disk', f'path={disk_path},format=qcow2,cache=unsafe',
            '--network', 'network=default',
            '--graphics', 'none', '--console', 'pty', '--rng', '/dev/urandom',
            # this has nothing to do with rhel8, it just tells v-i to use virtio
            '--os-variant', 'rhel8-unknown',
            '--noreboot', '--import',
        ]

        executable = util.libdir / 'pseudotty'
        util.subprocess_run(virt_install, executable=executable)

        self.orig_disk_path = disk_path
        self.orig_disk_format = 'qcow2'


def composer_cli(*args, log=True, check=True, **kwargs):
    run = util.subprocess_run if log else subprocess.run
    return run(['composer-cli', *args], check=check, **kwargs)


def composer_cli_out(*args, **kwargs):
    out = composer_cli(*args, stdout=subprocess.PIPE, universal_newlines=True, **kwargs)
    return out.stdout.rstrip('\n')

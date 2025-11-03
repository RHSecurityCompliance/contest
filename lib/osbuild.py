"""
Provides utilities for creating, importing and using Image Builder made images
for virtual machines, and a context manager to use them as VMs.

The classes and methods are derived from lib.virt, but instead of installing
VMs via Guest.install(), they are created from images via Guest.create().

    import osbuild

    osbuild.Host.setup()
    g = osbuild.Guest()

    # optional
    blueprint = osbuild.Blueprint()
    blueprint.add_something( ... )

    g.create(blueprint=blueprint)

    with g.booted():
        g.ssh( ... )
        g.ssh( ... )

Snapshotting is currently not supported/tested with this approach.
"""

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


class Host:
    @staticmethod
    def setup():
        virt.Host.setup()
        for unit in ['osbuild-composer.socket', 'osbuild-local-worker.socket']:
            ret = subprocess.run(['systemctl', 'is-active', '--quiet', unit])
            if ret.returncode != 0:
                util.subprocess_run(
                    ['systemctl', 'start', unit], check=True, stderr=subprocess.PIPE,
                )


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
        util.subprocess_run(
            ['systemctl', 'restart', 'osbuild-composer.service'],
            check=True, stderr=subprocess.PIPE,
        )
        yield
        shutil.rmtree(self.ETC_REPOS)
        util.subprocess_run(
            ['systemctl', 'restart', 'osbuild-composer.service'],
            check=True, stderr=subprocess.PIPE,
        )


class Compose:
    _Entry = collections.namedtuple(
        'ComposeEntry',
        ['id', 'status', 'blueprint', 'version', 'type'],
    )
    RUNNING_STATUSES = ['WAITING', 'RUNNING']
    FINISHED_STATUSES = ['FINISHED', 'FAILED']

    @classmethod
    def _get_status(cls, filter):
        out = composer_cli_out('compose', 'list', log=False)
        lines = iter(out.strip('\n').split('\n'))
        next(lines)  # skip header (first line)
        for line in lines:
            entry = cls._Entry(*re.split(r'[ \t]+', line))
            if filter(entry):
                return entry
        return None

    @classmethod
    def _wait_for_finished(cls, blueprint_name, sleep=1):
        entry = cls._get_status(lambda x: x.blueprint == blueprint_name)
        if not entry:
            raise FileNotFoundError(f"compose for {blueprint_name} not found in list")
        util.log(f"waiting for compose {entry.id} to be built")
        new = entry
        while new.status not in cls.FINISHED_STATUSES:
            new = cls._get_status(lambda x: x.id == entry.id)
            if not new:
                raise FileNotFoundError(f"compose {entry.id} disappeared")
            time.sleep(sleep)
        return new

    @classmethod
    @contextlib.contextmanager
    def build(cls, blueprint_name):
        entry = cls._get_status(lambda x: x.blueprint == blueprint_name)
        # delete any existing compose
        if entry:
            if entry.status in cls.RUNNING_STATUSES:
                composer_cli('compose', 'cancel', entry.id)
            composer_cli('compose', 'delete', entry.id)
        # start and wait
        composer_cli('compose', 'start', blueprint_name, 'qcow2')
        entry = cls._wait_for_finished(blueprint_name)
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
    TEMPLATE = util.dedent(fr'''
        name = "{NAME}"
        description = "Testing blueprint created by the Contest test suite"
        version = "1.0.0"
    ''')

    def __init__(self, template=TEMPLATE):
        self.assembled = f'{template}\n\n' if template else ''

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
            raise ValueError("openscap section not found")
        self.assembled = '\n'.join([
            pre,
            header.strip('\n'),
            f'datastream = "{ds_file}"',
            post,
        ])

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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.osbuild_log = f'{virt.GUEST_IMG_DIR}/{self.name}-osbuild.txt'

    def wipe(self):
        super().wipe()
        log = Path(self.osbuild_log)
        if log.exists():
            log.unlink()

    def install(*args, **kwargs):
        raise NotImplementedError("install() is not supported, use create()")

    def create_basic(self, *, blueprint=None, **kwargs):
        """
        Create a guest disk image via osbuild, and import it as a new guest
        domain into libvirt.

        If 'blueprint' is given as a 'class Blueprint' instance, it is used
        for further customizations instead of a fresh Blueprint instance.
        """
        util.log(f"creating guest {self.name}")

        if not blueprint:
            blueprint = Blueprint()

        image_path = Path(f'{virt.GUEST_IMG_DIR}/{self.name}.img')

        with blueprint.to_composer() as bp_name:
            # re-try multiple times to try to avoid a bug:
            # ERROR: Depsolve Error: Get "http://localhost/.../depsolve/contest_blueprint": EOF
            for _ in range(5):
                ret = composer_cli(
                    'blueprints', 'depsolve', bp_name, check=False, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
                sys.stdout.write(ret.stdout)
                if ret.returncode == 0:
                    break
                elif re.match(r'ERROR: Depsolve Error: Get "[^"]+": EOF\n', ret.stdout):
                    continue
                else:
                    raise RuntimeError(f"depsolve:\n{ret.stdout}")
            else:
                raise RuntimeError("depsolve failed, retries depleted")

            with Compose.build(bp_name) as ident:
                if image_path.exists():
                    image_path.unlink()
                composer_cli('compose', 'image', ident, '--filename', image_path)

                # get image building log, try to limit its size by cutting off
                # everything before openscap
                log = composer_cli_out('compose', 'log', ident)
                idx = log.find('Stage: org.osbuild.oscap')
                if idx != -1:
                    log = log[idx:]
                Path(self.osbuild_log).write_text(log)

        # import the created qcow2 image as a VM
        self.import_image(image_path, 'qcow2', **kwargs)

    def create(self, *, blueprint=None, rpmpack=None, **kwargs):
        """
        Create a guest disk image via osbuild, suitable for scanning
        via openscap.

        If custom 'rpmpack' is specified (RpmPack instance), it is used instead
        of a self-made instance.
        """
        # remove any previously installed guest
        self.wipe()

        if not blueprint:
            blueprint = Blueprint()

        # implicitly install openscap-scanner, like virt.Guest.install()
        blueprint.add_package('openscap-scanner')

        # generate an ssh key the same way as virt.Guest
        self.generate_ssh_keypair()
        blueprint.add_user('root', password=virt.GUEST_LOGIN_PASS, ssh_pubkey=self.ssh_pubkey)

        # osbuild doesn't support running Anaconda %post-style custom
        # scripts, the only way to run additional shell code is via
        # RPM scriptlets, so add custom guest setup via RpmPack
        pack = rpmpack or util.RpmPack()
        pack.add_host_repos()
        pack.add_sshd_late_start()
        # inherited from virt.Guest
        pack.requires += self.GUEST_REQUIRES
        with pack.build_as_repo() as repo:
            # ensure the custom RPM is added during image building
            blueprint.add_package(util.RpmPack.NAME)

            # osbuild-composer doesn't support file:// repos, so host
            # the custom RPM on a HTTP server
            with util.BackgroundHTTPServer('127.0.0.1', 0) as srv:
                srv.add_dir(repo, 'repo')
                http_host, http_port = srv.start()

                # overwrite default Red Hat CDN host repos via a custom HTTP server
                repos = ComposerRepos()
                repos.add_host_repos()
                repos.repos.append({
                    'name': 'contest-rpmpack',
                    'baseurl': f'http://{http_host}:{http_port}/repo',
                })
                with repos.to_composer():
                    # build qcow2 and import it
                    self.create_basic(blueprint=blueprint, **kwargs)


def composer_cli(*args, log=True, check=True, stderr=subprocess.PIPE, **kwargs):
    run = util.subprocess_run if log else subprocess.run
    return run(['composer-cli', *args], check=check, stderr=stderr, **kwargs)


def composer_cli_out(*args, **kwargs):
    out = composer_cli(*args, stdout=subprocess.PIPE, text=True, **kwargs)
    return out.stdout.rstrip('\n')


def translate_oscap_blueprint(lines, datastream):
    """
    Parse (and tweak) a blueprint generated via 'oscap xccdf generate fix'.
    """
    bp_text = '\n'.join(lines)

    # replace blueprint name, it's an unique identifier for composer-cli,
    # however replace only the first occurence of 'name', as later sections
    # like [[packages]] would also match ^name=...
    bp_text = re.sub(
        r'^name = .*',
        f'name = "{Blueprint.NAME}"',
        bp_text, count=1, flags=re.M,
    )

    blueprint = Blueprint(template=bp_text)

    # add openscap hardening, honor global excludes
    blueprint.set_openscap_datastream(datastream)

    return blueprint

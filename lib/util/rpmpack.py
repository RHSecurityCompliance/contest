import textwrap
import tempfile
import contextlib
from pathlib import Path

from .. import dnf
from .log import log
from .subprocess import subprocess_run
from .dedent import dedent

# we could use '%{_datadir}/%{name}' in the specfile, but this is more
# deterministic when used from other libs / tests
RPMPACK_NAME = 'contest-pack'
RPMPACK_FILE = 'contest-pack-1-1.noarch.rpm'
RPMPACK_DATA = '/usr/share/contest-pack'


class RpmPack:
    HEADER = dedent(fr'''
        Name: {RPMPACK_NAME}
        Summary: RPM content pack for the Contest test suite
        Version: 1
        Release: 1
        License: GPLv3
        BuildArch: noarch

        %global source_date_epoch_from_changelog 0

        %description
    ''')

    def __init__(self):
        # strings, bash scripts to be run during/after RPM installation
        self.post = []
        # Paths to files to be included in the RPM
        self.files = []
        # RPM names, hard-depend on them, run %post after them in a transaction
        self.requires = []
        # no hard RPM require dependencies, just run %post after these
        self.softreq = []

    # we intentionally don't track %dir and directories in general in %files
    # for simplicity reasons
    # - RPM does auto-create them on install, so the only issue is them being
    #   left there after RPM uninstall, which we don't care about here
    def add_file(self, source, target):
        """
        Add a file path to the RPM, 'source' specifies a file path on the host,
        'target' is the installed path in the RPM.
        """
        target = Path(target)
        if not target.is_absolute():
            raise SyntaxError(f"target {target} not an absolute path")
        self.files.append((Path(source).absolute(), target))

    def add_host_repos(self):
        for repofile in dnf.repo_files():
            self.add_file(repofile, repofile)

    def create_spec(self):
        install_block = files_block = ''
        created_dirs = set()
        for source, target in self.files:
            if target.parent not in created_dirs:
                install_block += f'mkdir -p "%{{buildroot}}{target.parent}"\n'
                created_dirs.add(target.parent)
            install_block += f'cp -r "{source}" "%{{buildroot}}{target}"\n'
            mode = '0755' if source.is_dir() else '0644'
            files_block += f'%attr({mode},root,root) {target}\n'
        # on rpm install only, not on upgrade
        post_block = '[ "$1" != 1 ] && exit 0\n'
        for script in self.post:
            post_block += f'(\n{script}\n) || exit $?\n'
        post_block += 'exit 0\n'
        return (
            (f'''Requires: {' '.join(self.requires)}\n''' if self.requires else '')
            + (f'''OrderWithRequires: {' '.join(self.softreq)}\n''' if self.softreq else '')
            + f'{self.HEADER}\n\n'
            + f'%install\n{install_block}\n'
            + f'%files\n{files_block}\n'
            + f'%post\n{post_block}'
        )

    @contextlib.contextmanager
    def build(self):
        """Build the binary RPM and return a path to a temporary .rpm file."""
        spec = self.create_spec()
        log(f"using specfile:\n{textwrap.indent(spec, '    ')}")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # write down the spec file
            specdir = tmpdir / 'SPECS'
            specdir.mkdir()
            specfile = specdir / f'{RPMPACK_NAME}.spec'
            specfile.write_text(spec)
            # build it via rpmbuild
            cmd = [
                'rpmbuild', '--define', f'_topdir {tmpdir.absolute()}',
                '-ba', specfile.absolute(),
            ]
            subprocess_run(cmd, check=True)
            # yield it to caller
            binrpm = tmpdir / 'RPMS' / 'noarch' / f'{RPMPACK_NAME}-1-1.noarch.rpm'
            if not binrpm.exists():
                raise RuntimeError("rpmbuild did not build the binary RPM")
            yield binrpm

    @contextlib.contextmanager
    def build_as_repo(self):
        """
        Build the binary RPM and return a path to a temporary directory with
        YUM/DNF metadata (serving as a repository) containing the binary RPM.
        """
        with self.build() as binrpm:
            repodir = binrpm.parent
            subprocess_run(['createrepo', repodir], check=True)
            yield repodir

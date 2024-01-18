import textwrap
import tempfile
import contextlib
from pathlib import Path

from .. import util

# we could use '%{_datadir}/%{name}' in the specfile, but this is more
# deterministic when used from other libs / tests
RPMPACK_NAME = 'contest-pack'
RPMPACK_DATA = '/usr/share/contest-pack'


class RpmPack:
    HEADER = util.dedent(fr'''
        Name: {RPMPACK_NAME}
        Summary: RPM content pack for the Contest test suite
        Version: 1
        Release: 1
        License: GPLv3
        BuildArch: noarch

        %global source_date_epoch_from_changelog 0
        %global contest_data {RPMPACK_DATA}
        %global build_data %{{buildroot}}{RPMPACK_DATA}

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

    def add_file(self, path, name=None):
        path = Path(path)
        if not name:
            name = path.name
        self.files.append((path, name))

    def create_spec(self):
        install_block = 'mkdir -p "%{build_data}"\n'
        files_block = '%attr(0755,root,root) %dir %{contest_data}\n'
        for path, name in self.files:
            install_block += f'cp "{path.absolute()}" "%{{build_data}}/{name}"\n'
            files_block += f'%attr(0644,root,root) %{{contest_data}}/{name}\n'
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
        util.log(f"using specfile:\n{textwrap.indent(spec, '    ')}")
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
            util.subprocess_run(cmd, check=True)
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
            util.subprocess_run(['createrepo', repodir], check=True)
            yield repodir

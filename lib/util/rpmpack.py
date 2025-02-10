import textwrap
import tempfile
import contextlib
import collections
from pathlib import Path

from lib import util, dnf


class RpmPack:
    NAME = 'contest-pack'
    VERSION = 1
    RELEASE = 1
    ARCH = 'noarch'
    HEADER = util.dedent(fr'''
        Name: {NAME}
        Summary: RPM content pack for the Contest test suite
        Version: {VERSION}
        Release: {RELEASE}
        License: GPLv3
        BuildArch: {ARCH}

        %global source_date_epoch_from_changelog 0

        %description
    ''')
    NVR = f'{NAME}-{VERSION}-{RELEASE}'
    FILE = f'{NVR}.{ARCH}.rpm'

    FilePath = collections.namedtuple('RpmPackFilePath', ['source', 'target'])
    FileContents = collections.namedtuple('RpmPackFileContents', ['target', 'contents'])

    def __init__(self):
        # strings, bash scripts to be run during/after RPM installation
        self.post = []
        # FilePath/FileContents to files to be included in the RPM
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
        entry = self.FilePath(Path(source).absolute(), target)
        self.files.append(entry)

    def add_file_contents(self, target, contents):
        """
        Add arbitrary text file contents as a file path in the RPM.
        Here, 'target' is the installed path in the RPM, and 'contents' are file
        contents to be installed at that path.
        """
        target = Path(target)
        if not target.is_absolute():
            raise SyntaxError(f"target {target} not an absolute path")
        entry = self.FileContents(target, contents)
        self.files.append(entry)

    def add_host_repos(self):
        for repofile in dnf.repo_files():
            self.add_file(repofile, repofile)

    def create_spec(self):
        install_block = files_block = ''
        created_dirs = set()

        for file in self.files:
            if file.target.parent not in created_dirs:
                install_block += f'mkdir -p "%{{buildroot}}{file.target.parent}"\n'
                created_dirs.add(file.target.parent)
            if isinstance(file, self.FilePath):
                install_block += f'cp -r "{file.source}" "%{{buildroot}}{file.target}"\n'
            elif isinstance(file, self.FileContents):
                install_block += f'''cat > "%{{buildroot}}{file.target}" <<'EOF'\n'''
                install_block += file.contents
                install_block += '\nEOF'
            else:
                raise RuntimeError(f"invalid file entry: {file}")
            files_block += f'%attr(0644,root,root) {file.target}\n'

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
            specfile = specdir / f'{self.NAME}.spec'
            specfile.write_text(spec)
            # build it via rpmbuild
            cmd = [
                'rpmbuild', '--define', f'_topdir {tmpdir.absolute()}',
                '-ba', specfile.absolute(),
            ]
            util.subprocess_run(cmd, check=True)
            # yield it to caller
            binrpm = tmpdir / 'RPMS' / self.ARCH / self.FILE
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

    def install(self):
        """
        Build the binary RPM and call 'dnf install' on it.
        """
        with self.build() as binrpm:
            util.subprocess_run(['dnf', 'install', '-y', binrpm], check=True)

    def uninstall(self):
        """
        Call 'dnf remove' on a previously-installed built RPM.
        """
        util.subprocess_run(['dnf', 'remove', '--noautoremove', '-y', self.NAME], check=True)

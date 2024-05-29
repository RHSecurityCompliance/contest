import os
import subprocess
import contextlib
import tempfile
from pathlib import Path

from lib import util, dnf
from lib.versions import rhel

user_content = os.environ.get('CONTEST_CONTENT')
if user_content:
    user_content = Path(user_content)


def find_datastream_in(root):
    base_dir = root / Path('usr/share/xml/scap/ssg/content')
    if rhel.is_true_rhel():
        return base_dir / f'ssg-rhel{rhel.major}-ds.xml'
    elif rhel.is_centos():
        if rhel <= 8:
            return base_dir / f'ssg-centos{rhel.major}-ds.xml'
        else:
            return base_dir / f'ssg-cs{rhel.major}-ds.xml'


def get_datastream():
    if user_content:
        build_content(user_content)
        datastream = user_content / 'build' / f'ssg-rhel{rhel.major}-ds.xml'
    else:
        datastream = find_datastream_in('/')
    if not datastream.exists():
        raise RuntimeError(f"could not find datastream as {datastream}")
    return datastream


def _find_playbooks():
    if user_content:
        build_content(user_content)
        return user_content / 'build' / 'ansible'
    else:
        return Path('/usr/share/scap-security-guide/ansible')


def get_playbook(profile):
    if rhel.is_true_rhel():
        name = f'rhel{rhel.major}-playbook-{profile}.yml'
    elif rhel.is_centos():
        if rhel <= 8:
            name = f'centos{rhel.major}-playbook-{profile}.yml'
        else:
            name = f'cs{rhel.major}-playbook-{profile}.yml'
    playbook = _find_playbooks() / name
    if not playbook.exists():
        raise RuntimeError(f"cound not find playbook as {playbook}")
    return playbook


def iter_playbooks():
    for name in _find_playbooks().rglob('*'):
        if name.suffix == '.yml':
            yield name


def get_kickstart(profile):
    if user_content:
        build_content(user_content)
        kickstart = (
            user_content / 'products' / f'rhel{rhel.major}' / 'kickstart'
            / f'ssg-rhel{rhel.major}-{profile}-ks.cfg'
        )
    else:
        base_dir = Path('/usr/share/scap-security-guide/kickstart')
        # RHEL and CentOS Stream both use 'ssg-rhel*' files
        kickstart = base_dir / f'ssg-rhel{rhel.major}-{profile}-ks.cfg'
    if not kickstart.exists():
        raise RuntimeError(f"cound not find kickstart as {kickstart}")
    return kickstart


def content_is_built(path):
    return (Path(path) / 'build' / f'ssg-rhel{rhel.major}-ds.xml').exists()


def build_content(path):
    if content_is_built(path):
        return
    util.log(f"building content from source in {path}")
    # install dependencies
    cmd = ['dnf', '-y', 'builddep', '--spec', 'scap-security-guide.spec']
    util.subprocess_run(cmd, check=True, cwd=path)
    # build content
    cmd = ['./build_product', f'rhel{rhel.major}']
    util.subprocess_run(cmd, check=True, cwd=path)


@contextlib.contextmanager
def get_content(build=True):
    """
    Acquire and return a path to a fully built content source,
    from either a user-provided directory or a SRPM.

    Optionally, specify build=False to save some time if you're accessing
    plain files or executing utils and need just the content source.
    """
    if user_content:
        if build:
            build_content(user_content)
        yield user_content
    else:
        # fall back to SRPM
        with dnf.download_rpm('scap-security-guide', source=True) as src_rpm:
            with tempfile.TemporaryDirectory() as tmpdir:
                # install dependencies
                cmd = ['dnf', '-y', 'builddep', '--srpm', src_rpm]
                util.subprocess_run(cmd, check=True, cwd=tmpdir)
                # extract + patch SRPM
                cmd = ['rpmbuild', '-rp', '--define', f'_topdir {tmpdir}', src_rpm]
                util.subprocess_run(cmd, check=True)
                # get path to the extracted content
                # - parse name+version from the SRPM instead of glob(BUILD/*)
                #   because of '-rhel6' content on RHEL-8
                ret = util.subprocess_run(
                    ['rpm', '-q', '--qf', '%{NAME}-%{VERSION}', '-p', src_rpm],
                    check=True, stdout=subprocess.PIPE, universal_newlines=True, cwd=tmpdir,
                )
                name_version = ret.stdout.strip()
                extracted = Path(tmpdir) / 'BUILD' / name_version
                util.log(f"using {extracted} as content source")
                if not extracted.exists():
                    raise FileNotFoundError(f"{extracted} not in extracted/patched SRPM")
                # build content
                if build:
                    cmd = ['./build_product', f'rhel{rhel.major}']
                    util.subprocess_run(cmd, check=True, cwd=extracted)
                yield extracted

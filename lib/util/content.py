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


def _find_datastreams(force_ssg):
    ssg_path = Path('/usr/share/xml/scap/ssg/content')
    # if specifically requested by the user
    if force_ssg:
        return ssg_path
    # if CONTEST_CONTENT was specified
    if user_content:
        return user_content / 'build'
    # default to the OS-wide scap-security-guide content
    return ssg_path


def get_datastream(force_ssg=False):
    if rhel.is_true_rhel():
        name = f'ssg-rhel{rhel.major}-ds.xml'
    elif rhel.is_centos():
        if rhel == 8:
            name = f'ssg-centos{rhel.major}-ds.xml'
        else:
            name = f'ssg-cs{rhel.major}-ds.xml'
    datastream = _find_datastreams(force_ssg) / name
    if not datastream.exists():
        raise RuntimeError(f"could not find datastream as {datastream}")
    return datastream


def iter_datastreams(force_ssg=False):
    for file in _find_datastreams(force_ssg).rglob('*'):
        # Return only DS v1.3, do not return v1.2 (ends with '-ds-1.2.xml')
        if file.name.endswith('-ds.xml'):
            yield file


def _find_playbooks(force_ssg):
    ssg_path = Path('/usr/share/scap-security-guide/ansible')
    # if specifically requested by the user
    if force_ssg:
        return ssg_path
    # if CONTEST_CONTENT was specified
    if user_content:
        return user_content / 'build' / 'ansible'
    # default to the OS-wide scap-security-guide content
    return ssg_path


def _find_per_rule_playbooks(force_ssg):
    ssg_path = Path(f'/usr/share/scap-security-guide/ansible/rule_playbooks/rhel{rhel.major}/all')
    # if specifically requested by the user
    if force_ssg:
        return ssg_path
    # if CONTEST_CONTENT was specified
    if user_content:
        return user_content / 'build' / f'rhel{rhel.major}' / 'playbooks' / 'all'
    # default to the OS-wide scap-security-guide content
    return ssg_path


def get_playbook(profile, force_ssg=False):
    if rhel.is_true_rhel():
        name = f'rhel{rhel.major}-playbook-{profile}.yml'
    elif rhel.is_centos():
        if rhel == 8:
            name = f'centos{rhel.major}-playbook-{profile}.yml'
        else:
            name = f'cs{rhel.major}-playbook-{profile}.yml'
    playbook = _find_playbooks(force_ssg) / name
    if not playbook.exists():
        raise RuntimeError(f"cound not find playbook as {playbook}")
    return playbook


def iter_playbooks(force_ssg=False):
    for file in _find_playbooks(force_ssg).iterdir():
        if file.suffix == '.yml':
            yield file
    per_rule_dir = _find_per_rule_playbooks(force_ssg)
    if per_rule_dir.exists():
        yield from per_rule_dir.iterdir()


def get_kickstart(profile):
    if user_content:
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


@contextlib.contextmanager
def get_content(build=True):
    """
    Acquire and return a path to a fully built content source,
    from either a user-provided directory or a SRPM.

    Optionally, specify build=False to save some time if you're accessing
    plain files or executing utils and need just the content source.
    """
    if user_content:
        # content already built by a TMT plan prepare step
        yield user_content
    else:
        # fall back to SRPM
        with dnf.download_rpm('scap-security-guide', source=True) as src_rpm:
            with tempfile.TemporaryDirectory() as tmpdir:
                # install dependencies
                cmd = ['dnf', '-y', 'builddep', src_rpm]
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
                # extracted sources directory varies across distro versions, thus
                # try to search for the directory rather than using hardcoded path
                try:
                    builddir = Path(tmpdir) / 'BUILD'
                    extracted = next(builddir.glob(f'**/{name_version}'))
                except StopIteration:
                    raise FileNotFoundError("extracted SRPM content sources not found")
                util.log(f"using {extracted} as content source")
                # build content
                if build:
                    cmd = ['./build_product', '--playbook-per-rule', f'rhel{rhel.major}']
                    util.subprocess_run(cmd, check=True, cwd=extracted)
                yield extracted

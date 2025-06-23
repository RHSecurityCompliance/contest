"""
These are support functions for testing "old content", the previous released
content version, typically in comparison to "new content", the current release.
"""

import subprocess
import functools
import contextlib

from lib import util, dnf


@contextlib.contextmanager
def _downloaded_extracted_ds(version):
    with dnf.download_rpm(f'scap-security-guide-{version}') as rpm:
        with dnf.extract_rpm(rpm) as extracted:
            datastream = util.get_datastream(extracted)
            if not datastream.exists():
                raise RuntimeError(f"could not find datastream as {datastream}")
            yield datastream


def _installed_ssg_version():
    cmd = ['rpm', '-q', '--qf', '%{VERSION}-%{RELEASE}', 'scap-security-guide']
    ret = util.subprocess_run(cmd, stdout=subprocess.PIPE, text=True)
    if ret.returncode != 0:
        util.log(f"rpm: {ret.stdout}")
        ret.check_returncode()
    return ret.stdout


def _compare_ssg_versions(ver_a, ver_b):
    cmd = ['rpm', '--eval', f'%{{lua:print(rpm.vercmp("{ver_a}", "{ver_b}"))}}']
    ret = util.subprocess_run(cmd, stdout=subprocess.PIPE, text=True)
    return int(ret.stdout)


def _available_ssg_versions():
    cmd = [
        'dnf', '-q', 'repoquery', '--available', '--arch', 'noarch',
        '--qf', '%{VERSION}-%{RELEASE}', 'scap-security-guide',
    ]
    ret = util.subprocess_run(cmd, check=True, stdout=subprocess.PIPE, text=True)
    versions = ret.stdout.rstrip('\n').split('\n')
    # sort from newest to oldest
    return sorted(versions, key=functools.cmp_to_key(_compare_ssg_versions), reverse=True)


@contextlib.contextmanager
def get_old_datastream():
    # installed SSG with datastream in /usr/share/xml
    installed = _installed_ssg_version()
    ssg_datastream = util.get_datastream(force_ssg=True)
    if not ssg_datastream.exists():
        raise RuntimeError(f"DS not found on {ssg_datastream}, no clue what to diff")

    # "new" content is CONTEST_CONTENT,
    # "old" is the installed scap-security-guide RPM
    user_content = util.get_user_content(build=False)
    if user_content:
        yield ssg_datastream

    # "new" is the installed scap-security-guide RPM,
    # "old" is an older version available in YUM/DNF repositories
    else:
        available = _available_ssg_versions()
        if not available:
            raise RuntimeError("found no available SSG RPM versions in YUM/DNF repositories")
        if installed != available[0]:
            raise RuntimeError(
                f"installed SSG {installed} is not the latest available ({available[0]})",
            )
        if len(available) < 2:
            raise RuntimeError(
                f"repoquery returned only 1 (currently installed) SSG version ({available[0]}), "
                "no clue what to use as 'old'",
            )
        old = available[1]
        with _downloaded_extracted_ds(old) as ds:
            util.log("using new from installed SSG RPM, old from previous SSG RPM")
            yield ds

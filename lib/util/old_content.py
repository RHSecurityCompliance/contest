"""
These are support functions for testing "old content", the previous released
content version, typically in comparison to "new content", the current release.
"""

import subprocess
import functools
import contextlib
import rpm

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
    ret = util.subprocess_run(cmd, stdout=subprocess.PIPE, universal_newlines=True)
    if ret.returncode != 0:
        util.log(f"rpm: {ret.stdout}")
        ret.check_returncode()
    return ret.stdout


def _available_ssg_versions():
    cmd = [
        'dnf', '-q', 'repoquery', '--available', '--arch', 'noarch',
        '--qf', '%{VERSION}-%{RELEASE}', 'scap-security-guide',
    ]
    ret = util.subprocess_run(cmd, check=True, stdout=subprocess.PIPE, universal_newlines=True)
    versions = ret.stdout.rstrip('\n').split('\n')
    # transform a list of NVRs to (name, version, release) tuples,
    # older rpm.labelCompare requires it
    versions = ((None, x, None) for x in versions)
    # sort from newest to oldest
    ordered = sorted(versions, key=functools.cmp_to_key(rpm.labelCompare), reverse=True)
    return [version for _, version, _ in ordered]


@contextlib.contextmanager
def get_old_datastream():
    # installed SSG with datastream in /usr/share/xml
    installed = _installed_ssg_version()
    root_datastream = util.get_datastream('/')
    if not root_datastream.exists():
        raise RuntimeError("DS not found on {root_datastream}, no clue what to diff")

    # "new" content is CONTEST_CONTENT,
    # "old" is the installed scap-security-guide RPM
    if util.user_content:
        yield root_datastream

    # "new" is the installed scap-security-guide RPM,
    # "old" is an older version available in YUM/DNF repositories
    else:
        available = _available_ssg_versions()
        if not available:
            raise RuntimeError("found no available SSG RPM versions in YUM/DNF repositories")
        if installed != available[0]:
            raise RuntimeError(
                f"installed SSG {installed} is not the latest available ({available[0]})"
            )
        if len(available) < 2:
            raise RuntimeError(
                f"repoquery returned only 1 (currently installed) SSG version ({available[0]}), "
                "no clue what to use as 'old'"
            )
        old = available[1]
        with _downloaded_extracted_ds(old) as ds:
            util.log("using new from installed SSG RPM, old from previous SSG RPM")
            yield ds

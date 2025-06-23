"""
Utility functions for acquiring binary/source CaC/content.

Content can come from two sources:
 - CONTEST_CONTENT as a git-repo-style directory
 - scap-security-guide RPM

Each of these has binary/sources on different places:
 - CONTEST_CONTENT
   - binary content needs to be built, is located in build/*
   - source content already exists as the directory itself
 - scap-security-guide RPM
   - binary content already exists in /usr/share
   - source content needs to be downloaded as SRPM

Unifying these under one API is therefore a significant challenge,
especially since the scap-security-guide RPM fragments binary content
to multiple paths in /usr/share.

This module therefore provides
 - several get_*() functions for getting binary content
   - if CONTEST_CONTENT is used, the content is built as-needed
 - one get_content_source() function for getting source content
   - if scap-security-guide RPM is used, a SRPM gets downloaded + extracted

The get_*() functions for binary content prefer CONTEST_CONTENT (if it is
defined) over the scap-security-guide RPM content. This can be overriden
with a function argument.

It is assumed only one process/thread is using either content location,
and downloaded SRPM sources or built CONTEST_CONTENT content is left
for further tests to be re-used if possible.

If a test needs binary content built with specific flags/options, or access
any binary artifacts other than what is provided here via get_*(), it should
get_source_content() and call build_content() on it, or build it itself.
"""

import os
import shutil
import subprocess
import contextlib
import tempfile
from pathlib import Path

from lib import util, dnf, versions
from lib.versions import rhel

CONTENT_BUILD_DIR = 'build'


def get_user_content(build=True):
    user_content = os.environ.get('CONTEST_CONTENT')
    if not user_content:
        return None
    user_content = Path(user_content).absolute()
    # variable defined, but path specified does not exist
    if not user_content.exists():
        raise RuntimeError(f"CONTEST_CONTENT={user_content} does not exist")
    if build:
        build_content(user_content)
    return user_content


def find_datastreams(force_ssg, content_dir=None):
    ssg_path = Path('/usr/share/xml/scap/ssg/content')
    # if specifically requested by the user
    if force_ssg:
        return ssg_path
    # if given content dir override or if CONTEST_CONTENT was specified
    user_content = content_dir or get_user_content()
    if user_content:
        return user_content / CONTENT_BUILD_DIR
    # default to the OS-wide scap-security-guide content
    return ssg_path


def get_datastream(force_ssg=False, content_dir=None):
    if rhel.is_true_rhel():
        name = f'ssg-rhel{rhel.major}-ds.xml'
    elif rhel.is_centos():
        if rhel == 8:
            name = f'ssg-centos{rhel.major}-ds.xml'
        else:
            name = f'ssg-cs{rhel.major}-ds.xml'
    datastream = find_datastreams(force_ssg, content_dir) / name
    if not datastream.exists():
        raise RuntimeError(f"could not find datastream as {datastream}")
    return datastream


def iter_datastreams(force_ssg=False, content_dir=None):
    for file in find_datastreams(force_ssg, content_dir).rglob('*'):
        # Return only DS v1.3, do not return v1.2 (ends with '-ds-1.2.xml')
        if file.name.endswith('-ds.xml'):
            yield file


def find_playbooks(force_ssg=False, content_dir=None):
    ssg_path = Path('/usr/share/scap-security-guide/ansible')
    # if specifically requested by the user
    if force_ssg:
        return ssg_path
    # if given content dir override or if CONTEST_CONTENT was specified
    user_content = content_dir or get_user_content()
    if user_content:
        return user_content / CONTENT_BUILD_DIR / 'ansible'
    # default to the OS-wide scap-security-guide content
    return ssg_path


def find_per_rule_playbooks(force_ssg=False, content_dir=None):
    ssg_path = Path(f'/usr/share/scap-security-guide/ansible/rule_playbooks/rhel{rhel.major}/all')
    # if specifically requested by the user
    if force_ssg:
        return ssg_path
    # if given content dir override or if CONTEST_CONTENT was specified
    user_content = content_dir or get_user_content()
    if user_content:
        return user_content / CONTENT_BUILD_DIR / f'rhel{rhel.major}' / 'playbooks' / 'all'
    # default to the OS-wide scap-security-guide content
    return ssg_path


def get_playbook(profile, force_ssg=False, content_dir=None):
    if rhel.is_true_rhel():
        name = f'rhel{rhel.major}-playbook-{profile}.yml'
    elif rhel.is_centos():
        if rhel == 8:
            name = f'centos{rhel.major}-playbook-{profile}.yml'
        else:
            name = f'cs{rhel.major}-playbook-{profile}.yml'
    playbook = find_playbooks(force_ssg, content_dir) / name
    if not playbook.exists():
        raise RuntimeError(f"cound not find playbook as {playbook}")
    return playbook


def iter_playbooks(force_ssg=False, content_dir=None):
    for file in find_playbooks(force_ssg, content_dir).iterdir():
        if file.suffix == '.yml':
            yield file
    per_rule_dir = find_per_rule_playbooks(force_ssg, content_dir)
    if per_rule_dir.exists():
        yield from per_rule_dir.iterdir()


def get_kickstart(profile, content_dir=None):
    # if given content dir override or if CONTEST_CONTENT was specified
    user_content = content_dir or get_user_content()
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


def _parse_cmake_config(path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(('#','//')) or '=' not in line:
                continue
            name, _, value = line.partition('=')
            yield (name, value)


def build_content(path, extra_cmake_opts=None, force=False):
    """
    Given a CaC/content source as 'path', build it with some sensible CMake
    options.

    Specify any additional ones as 'extra_cmake_opts' (dict); make sure to use
    the full option name with :DATATYPE as visible in CMakeCache.txt.
    See also https://cmake.org/cmake/help/latest/prop_cache/TYPE.html.

    Set 'force=True' to always re-build content, even with compatible options.
    """
    path = Path(path)
    build_dir = path / CONTENT_BUILD_DIR
    extra_cmake_opts = extra_cmake_opts or {}

    # assemble CMake options
    cmake_opts = {
        'CMAKE_BUILD_TYPE:STRING': 'Release',
        'SSG_CENTOS_DERIVATIVES_ENABLED:BOOL': 'ON' if versions.rhel.is_centos() else 'OFF',
        'SSG_PRODUCT_DEFAULT:BOOL': 'OFF',
        f'SSG_PRODUCT_RHEL{versions.rhel.major}:BOOL': 'ON',
        'SSG_SCE_ENABLED:BOOL': 'ON',
        'SSG_BASH_SCRIPTS_ENABLED:BOOL': 'OFF',
        'SSG_BUILD_DISA_DELTA_FILES:BOOL': 'OFF',
        'SSG_SEPARATE_SCAP_FILES_ENABLED:BOOL': 'OFF',
    }
    cmake_opts.update(extra_cmake_opts)

    # if there is pre-built content, check if it was built with options
    # we care about - if it was, do not rebuild it
    cmake_cache = build_dir / 'CMakeCache.txt'
    if cmake_cache.exists() and not force:
        built_opts = dict(_parse_cmake_config(cmake_cache))
        for key, value in cmake_opts.items():
            if key not in built_opts or value != built_opts[key]:
                break
        else:
            # all opts were ignored or passed equality checking
            return

    # install dependencies from an upstream-bundled spec file
    cmd = ['dnf', '-y', 'builddep', '--spec', path / 'scap-security-guide.spec']
    util.subprocess_run(cmd, check=True)

    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir()

    cli_opts = (f'-D{name}={val}' for name, val in cmake_opts.items())
    util.subprocess_run(['cmake', '../', *cli_opts], cwd=build_dir, check=True)

    cpus = os.cpu_count() or 1
    util.subprocess_run(['make', f'-j{cpus}'], cwd=build_dir, check=True)


@contextlib.contextmanager
def get_source_content():
    """
    Acquire and return a path to a CaC/content style content source distribution
    from either a user-provided directory or a SRPM.
    """
    user_content = get_user_content(build=False)
    if user_content:
        yield user_content
    else:
        # fall back to SRPM
        with dnf.download_rpm('scap-security-guide', source=True) as src_rpm:
            with tempfile.TemporaryDirectory() as tmpdir:
                # install dependencies
                # - unfortunately, we cannot move this to build_content()
                #   because extracting + patching SRPM needs all builddeps
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
                    check=True, stdout=subprocess.PIPE, text=True, cwd=tmpdir,
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
                yield extracted

#!/usr/bin/python3

import re
from pathlib import Path

from lib import util, results, versions


def download_source(package):
    """
    Download src rpm and return Path of the file.

    'package' is name of package to download.
    """
    util.subprocess_run(['yumdownloader', '--source', package], check=True)
    package_glob = package + '*.src.rpm'
    try:
        src_path = next(Path.cwd().glob(package_glob))
    except StopIteration:
        raise FileNotFoundError(f".src.rpm not found for {package}")
    return src_path


def build_source(src_rpm, path=None):
    """
    Build package from src rpm.

    'src_rpm' is path to src rpm file.
    Define 'path' to specify path where to build. Otherwise, build
    is done to rpmbuild directory in current working directory.
    """
    builddep_cmd = ['yum-builddep'] if versions.rhel == 7 else ['dnf', 'builddep']
    util.subprocess_run([*builddep_cmd, '-y', src_rpm], check=True)

    path = Path(path) if path else Path.cwd() / 'rpmbuild'

    util.subprocess_run(['rpm', '-ivh', '--define', f'_topdir {path}', src_rpm], check=True)

    spec_path = next((path / 'SPECS').glob('*.spec'))
    util.subprocess_run(['rpmbuild', '-bc', '--define', f'_topdir {path}', spec_path], check=True)

    return path


# Get src rpm and build from it
src_rpm = download_source('scap-security-guide')
rpm_build = build_source(src_rpm)
ssg_build = next((rpm_build / 'BUILD').glob('*/build'))

# ctest
cmd = ['cmake', '--build', ssg_build,
       '--target', 'test', '--', 'ARGS=--output-on-failure --output-log ctest_results']
util.subprocess_run(cmd)

with open(ssg_build / 'ctest_results') as f:
    # Result format: X/Y Test  #X: test_name .................  test_result   Z sec
    result_regex = re.compile(r'\d+\s+Test\s+#\d+:\s+([^\s]+)\s+\.+\s+(\w+)\s+')
    for line in f:
        result_match = result_regex.search(line)
        if result_match:
            test_name = result_match.group(1)
            if result_match.group(2) == 'Passed':
                result = 'pass'
            else:
                result = 'fail'
            results.report(result, test_name)

results.report_and_exit(logs=[ssg_build / 'Testing' / 'Temporary' / 'LastTest.log'])

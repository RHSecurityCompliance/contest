#!/usr/bin/python3

import re

from lib import util, results, versions


# options are taken from scap-security-guide spec file
if versions.rhel.is_true_rhel():
    cmake_options = [
        f'-DSSG_PRODUCT_RHEL{versions.rhel.major}:BOOLEAN=TRUE',
        '-DSSG_PRODUCT_DEFAULT:BOOLEAN=FALSE',
        '-DSSG_SCIENTIFIC_LINUX_DERIVATIVES_ENABLED:BOOL=OFF',
        '-DSSG_CENTOS_DERIVATIVES_ENABLED:BOOL=OFF',
        '-DSSG_ANSIBLE_PLAYBOOKS_PER_RULE_ENABLED:BOOL=ON',
    ]
elif versions.rhel.is_centos():
    cmake_options = [
        f'-DSSG_PRODUCT_RHEL{versions.rhel.major}:BOOLEAN=TRUE',
        '-DSSG_PRODUCT_DEFAULT:BOOLEAN=FALSE',
        '-DSSG_SCIENTIFIC_LINUX_DERIVATIVES_ENABLED:BOOL=OFF',
        '-DSSG_CENTOS_DERIVATIVES_ENABLED:BOOL=ON',
        '-DSSG_ANSIBLE_PLAYBOOKS_PER_RULE_ENABLED:BOOL=ON',
    ]
else:
    cmake_options = [
        '-DSSG_SEPARATE_SCAP_FILES_ENABLED=OFF',
        '-DSSG_BASH_SCRIPTS_ENABLED=OFF',
        '-DSSG_BUILD_SCAP_12_DS=OFF',
    ]

# Extra modules to enable more unit tests
python_modules = ['lxml', 'pytest', 'trestle', 'openpyxl', 'pandas', 'cmakelint']
util.subprocess_run(['python3', '-m', 'pip', 'install', *python_modules])

with util.get_content(build=False) as content_dir:
    build_dir = content_dir / 'build'

    util.subprocess_run(['cmake', '../', *cmake_options], cwd=build_dir, check=True)
    util.subprocess_run(['make', '-j4'], cwd=build_dir, check=True)

    # ctest
    cmd = [
        'cmake', '--build', build_dir, '--target', 'test',
        '--', 'ARGS=--output-on-failure --output-log ctest_results',
    ]
    util.subprocess_run(cmd, cwd=build_dir)

    with open(build_dir / 'ctest_results') as f:
        # Result format: X/Y Test  #X: test_name .................  test_result   Z sec
        result_regex = re.compile(r'\d+\s+Test\s+#\d+:\s+([^\s]+)\s+\.+')
        for line in f:
            result_match = result_regex.search(line)
            if result_match:
                test_name = result_match.group(1)
                result = 'pass' if 'Passed' in line else 'fail'
                results.report(result, test_name)

    results.report_and_exit(logs=[build_dir / 'Testing' / 'Temporary' / 'LastTest.log'])

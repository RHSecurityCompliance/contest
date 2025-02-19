#!/usr/bin/python3

import re

from lib import util, results, ansible


ansible.install_deps()
# Extra modules to enable more unit tests
python_modules = ['lxml', 'pytest', 'trestle', 'openpyxl', 'cmakelint']
util.subprocess_run(['python3', '-m', 'pip', 'install', *python_modules])

with util.get_source_content() as content_dir:
    # force a build, because CTest uses absolute paths somewhere in the built
    # content, which breaks when the content was pre-build elsewhere
    util.build_content(
        content_dir,
        {'SSG_ANSIBLE_PLAYBOOKS_PER_RULE_ENABLED:BOOL': 'ON'},
        force=True,
    )
    build_dir = content_dir / util.CONTENT_BUILD_DIR

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

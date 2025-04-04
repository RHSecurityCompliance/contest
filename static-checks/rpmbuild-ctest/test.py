#!/usr/bin/python3

import re

from pathlib import Path
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

    with open(build_dir / 'Testing' / 'Temporary' / 'LastTest.log') as f:
        state = 'start'
        test_output = []

        for line in f:
            line = line.rstrip('\n')

            if state == 'output':
                test_output.append(line)
                if line == '<end of output>':
                    state = 'after_output'
                continue

            if state == 'after_output' and re.match(r'^-{10,}\s*$', line):
                test_output.append(line)
                state = 'result'
                continue

            if state == 'start':
                if m := re.fullmatch(r'^[0-9]+/[0-9]+\s+Testing:\s+(.+)$', line):
                    test_name = m.group(1)
                    test_output.append(line)
                    state = 'output'
                    continue

            if state == 'result':
                test_output.append(line)
                if 'Test Passed' in line:
                    results.report('pass', test_name)
                else:
                    test_log = f'{test_name}.log'
                    Path(test_log).write_text('\n'.join(test_output))
                    results.report('fail', test_name, logs=[test_log])
                test_output.clear()
                state = 'start'

    results.report_and_exit()

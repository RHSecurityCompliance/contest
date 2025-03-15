#!/usr/bin/python3

import io

from lib import util, results, versions, unit_tests


def check_file(partial, test_file):
    if test_file.stat().st_size == 0:
        return "file is empty"

    # last line must have a terminating \n
    with open(test_file, 'rb') as f:
        f.seek(-1, io.SEEK_END)
        if f.read() != b'\n':
            return "last line doesn't end with a newline"

    with open(test_file) as f:
        # first line must be shebang
        line = next(f)
        if line != '#!/bin/bash\n':
            return "first line is not a /bin/bash shebang"

        try:
            filled = unit_tests.fill_in_metadata(partial, f)
        except ValueError as e:
            return f"metadata syntax error: {str(e)}"

        if filled.remediation:
            if filled.remediation not in ['bash', 'ansible', 'none']:
                return f"remediation={filled.remediation} is not valid"
        if filled.check:
            if filled.check not in ['oval', 'sce', 'any']:
                return f"check={filled.check} is not valid"
        if filled.remediation and filled.is_pass:
            return f"remediation={filled.remediation} doesn't make sense for a .pass.sh test"

        # metadata parsing stopped because it hit either EOF or non-metadata
        # code, so a repeated attempt must not find any metadata
        try:
            filled = unit_tests.fill_in_metadata(partial, f)
        except ValueError as e:
            return f"metadata syntax error: {str(e)}"
        if filled.packages:
            return "packages defined after non-metadata code"
        if filled.profiles:
            return "profiles defined after non-metadata code"
        if filled.variables:
            return "variables defined after non-metadata code"
        if filled.remediation:
            return "remediation defined after non-metadata code"
        if filled.check:
            return "check defined after non-metadata code"


with util.get_source_content() as content_dir:
    util.build_content(
        content_dir,
        {'SSG_BUILT_TESTS_ENABLED:BOOL': 'ON'},
    )
    build_dir = content_dir / util.CONTENT_BUILD_DIR
    built_tests = build_dir / f'rhel{versions.rhel.major}' / 'tests'
    util.log(f"using built tests: {str(built_tests)}")

    for rule_dir in unit_tests.iter_rules(built_tests):
        for partial, test_file in unit_tests.iter_tests(rule_dir):
            pass_fail = 'pass' if partial.is_pass else 'fail'
            result_name = f'{partial.rule}/{partial.test}.{pass_fail}'
            if problem := check_file(partial, test_file):
                results.report('fail', result_name, problem)
            else:
                results.report('pass', result_name)

results.report_and_exit()

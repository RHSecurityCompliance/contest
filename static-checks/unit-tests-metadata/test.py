#!/usr/bin/python3

import io
#from pathlib import Path

from lib import util, results, versions, unit_tests

#valid_meta_lines = [
#    re.compile(r'# packages ='),
#    re.compile(r'# platform ='),
#    re.compile(r'# profiles ='),
#    re.compile(r'# check ='),
#    re.compile(r'# remediation ='),
#    re.compile(r'# templates ='),
#    re.compile(r'# variables ='),
#]


#def check_test(test_file):
#    size = test_file.stat().st_size
#    if size == 0:
#        return "file is empty"
#
#    with open(test_file) as f:
#        # first line must be shebang
#        line = next(f)
#        #if line != '#!/bin/bash\n':
#        #    return "first line is not a /bin/bash shebang"
#        lineno = 0
#
#        # skip empty lines / comments / valid metadata
#        for lineno, line in enumerate(f, start=lineno+1):
#            util.log(f"evaluating {lineno}: {line}")
#            if not line.endswith('\n'):
#                return "last line doesn't end with a newline"
#
#            line = line.rstrip('\n')
#
#            # empty line or line with spaces
#            if not line or re.fullmatch(r'^\s+$', line):
#                continue
#            # any comment (incl. metadata)
#            if line.startswith('#'):
#                continue
#
#            # non-comment (non-metadata) line found
#            break
#
#        # there must not be any metadata beyond non-metadata content
#        for lineno, line in enumerate(f, start=lineno+1):
#            util.log(f"evaluating2 {lineno}: {line}")
#            #for rgx in valid_meta_lines:
#            #    util.log(f"trying: {rgx}, match: {rgx.match(line)} ; line: {line}")
#            # valid metadata line
#            if any(r.match(line) for r in valid_meta_lines):
#                return f"metadata found after non-metadata content on line {lineno}"
#
#        return None

def check_file(partial, test_file):
    size = test_file.stat().st_size
    if size == 0:
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

        filled = unit_tests.fill_in_metadata(partial, f)

        if filled.remediation:
            if filled.remediation not in ['bash', 'ansible', 'none']:
                return f"remediation={filled.remediation} is not valid"
        if filled.check:
            if filled.check not in ['oval', 'sce', 'any']:
                return f"check={filled.check} is not valid"

        # metadata parsing stopped because it hit either EOF or non-metadata
        # code, so a repeated attempt must not find any metadata
        filled = unit_tests.fill_in_metadata(partial, f)
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
        {
            'SSG_BUILT_TESTS_ENABLED:BOOL': 'ON',
        },
    )
    build_dir = content_dir / util.CONTENT_BUILD_DIR
    built_tests = build_dir / f'rhel{versions.rhel.major}' / 'tests'
    util.log(f"using built tests: {str(built_tests)}")

    for partial, test_file in unit_tests.iter_tests(built_tests):
        util.log(f"CHECKING: {partial}")
        result_name = f'{partial.rule}/{partial.test}'
        problem = check_file(partial, test_file)
        if problem:
            results.report('fail', result_name, problem)
        else:
            results.report('pass', result_name)

results.report_and_exit()

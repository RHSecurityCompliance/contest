import re
import io
import contextlib
import collections
from pathlib import Path


UnitTest = collections.namedtuple(
    'UnitTest',
    [
        # str: rule name
        'rule',
        # str: test name without .pass.sh or .fail.sh
        'test',
        # bool: True if .pass.sh, False if .fail.sh
        'is_pass',
        # tuple of str or None: RPM package names
        'packages',
        # tuple of str or None: profiles the test should be run within
        'profiles',
        # dict or None: variables that should be changed in datastream/playbook
        'variables',
        # str or None: which remediation types should be tested (none, bash, ansible, ..)
        'remediation',
        # str or None: check engine type
        'check',
    ],
    # last 5 fields are optional
    defaults=[None, None, None, None, None],
)


def fill_in_metadata(unit_test, test_file):
    """
    Given an (incomplete) UnitTest tuple as 'unit_test', fill in values
    from unit test file metadata, returning the complete UnitTest.

    'test_file' may be a file path or a file-like object.
    """
    packages = set()
    profiles = set()
    variables = {}
    remediation = None
    check = None

    with contextlib.ExitStack() as stack:
        if isinstance(test_file, io.IOBase):
            f = test_file
        else:
            f = stack.enter_context(open(test_file))

        for line in f:
            line = line.rstrip('\n')
            # skip empty lines and comments
            if not line or re.fullmatch(r'\s+', line):
                continue
            # packages
            m = re.fullmatch(r'# packages = (.+)', line)
            if m:
                packages.update(re.split(r'[, ]+', m.group(1)))
                continue
            # profiles
            m = re.fullmatch(r'# profiles = (.+)', line)
            if m:
                profiles.update(re.split(r'[, ]+', m.group(1)))
                continue
            # variables
            m = re.fullmatch(r'# variables = (.+)', line)
            if m:
                key, value = re.split(r'[= ]+', m.group(1), maxsplit=1)
                variables[key] = value
                continue
            # remediation
            m = re.fullmatch(r'# remediation = (.+)', line)
            if m:
                remediation = m.group(1)
                continue
            # check
            m = re.fullmatch(r'# check = (.+)', line)
            if m:
                check = m.group(1)
                continue
            # other unrecognized comments
            if line.startswith('#'):
                continue
            # first non-metadata line hit, abort parsing
            break

    return unit_test._replace(
        # save memory by using const tuples
        packages=tuple(packages) if packages else None,
        profiles=tuple(profiles) if profiles else None,
        variables=variables or None,
        remediation=remediation,
        check=check,
    )


def iter_tests(tests_dir):
    """
    Given a directory with built tests, yield tuples of
    (partial UnitTest , test file path).
    """
    for rule_dir in sorted(Path(tests_dir).iterdir(), key=lambda x: x.name):
        # tests are inside rule-named directories, skip non-dir files
        if not rule_dir.is_dir():
            continue
        for test_file in sorted(rule_dir.iterdir(), key=lambda x: x.name):
            file_name = test_file.name
            if file_name.endswith('.pass.sh'):
                test = file_name.removesuffix('.pass.sh')
                is_pass = True
            elif file_name.endswith('.fail.sh'):
                test = file_name.removesuffix('.fail.sh')
                is_pass = False
            else:
                # skip non-test files that might be present
                continue
            yield (UnitTest(rule_dir.name, test, is_pass), test_file)


def collect_unit_tests(tests_dir):
    """
    Given a directory with built tests, yield fully resolved UnitTest
    instances (incl. in-test '# key = value' metadata).
    """
    for partial, test_file in iter_tests(tests_dir):
        yield fill_in_metadata(partial, test_file)

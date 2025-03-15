"""
These are utilities for working with CaC/content unit tests, as built by
the CaC/content built system.

To satisfy various use cases, the logic is modularized into functions:

 - iter_rules() iterates over all built tests, yielding rules

 - iter_tests() iterates over .sh tests for one rule, yielding partial
   UnitTest with info from the rule directory (rule, test, is_pass)

 - fill_in_metadata() reads the .sh contents and completes UnitTest
   based on metadata contained in the .sh file
"""

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


# a=b,c=d,e=f  --> {'a': 'b', 'c': 'd', 'e': 'f'}
# a=b,c        --> {'a': 'b,c'}
# a=b , c      --> {'a': 'b , c'}           # preserved space
# a=b, c ,d=e  --> {'a': 'b, c', 'd': 'e'}
# a=b, c=d     --> {'a': 'b', 'c': 'd'}
# a=b,c= d     --> {'a': 'b', 'c': 'd'}
# a=b,c =d     --> {'a': 'b', 'c': 'd'}
# a=b, c = d   --> {'a': 'b', 'c': 'd'}
# a=b , c = d  --> {'a': 'b', 'c': 'd'}
# a=,b=c       --> {'a': '', 'b': 'c'}
# a=b,=c       --> error key empty
# a            --> error missing key
def parse_variables(line):
    variables = {}
    key = None
    for part in line.split(','):
        if '=' in part:
            key, _, value = part.partition('=')
            key = key.strip()
            value = value.lstrip()
            if not key:
                raise ValueError(f"key empty: {part}")
            variables[key] = value
        else:
            if key is None:
                raise ValueError(f"no key=value pair given: {part}")
            variables[key] += f',{part}'
    # trim any trailing spaces in values
    # (we need to do it here because we might have added space-containing
    #  equals-less extra values to a previous key via the 'else' branch)
    for key, value in variables.items():
        variables[key] = value.rstrip()
    return variables


def fill_in_metadata(unit_test, test_file):
    """
    Given an (incomplete) UnitTest tuple as 'unit_test', fill in values
    from unit test file metadata, returning the complete UnitTest.

    'test_file' may be a file path or a file-like object.
    """
    packages = None
    profiles = None
    variables = None
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
            if m := re.fullmatch(r'# packages = (.+)', line):
                if packages is not None:
                    raise ValueError(f"packages already defined as: {packages}")
                # save memory by using const tuples
                packages = tuple(re.split(r' *, *', m.group(1)))
                continue
            # profiles
            if m := re.fullmatch(r'# profiles = (.+)', line):
                if profiles is not None:
                    raise ValueError(f"profiles already defined as: {profiles}")
                # save memory by using const tuples
                profiles = tuple(re.split(r' *, *', m.group(1)))
                continue
            # variables
            if m := re.fullmatch(r'# variables = (.+)', line):
                if variables is not None:
                    raise ValueError(f"variables already defined as: {variables}")
                variables = parse_variables(m.group(1))
                continue
            # remediation
            if m := re.fullmatch(r'# remediation = (.+)', line):
                if remediation is not None:
                    raise ValueError(f"remediation already defined as: {remediation}")
                remediation = m.group(1)
                continue
            # check
            if m := re.fullmatch(r'# check = (.+)', line):
                if check is not None:
                    raise ValueError(f"check already defined as: {check}")
                check = m.group(1)
                continue
            # other unrecognized comments
            if line.startswith('#'):
                continue
            # first non-metadata line hit, abort parsing
            break

    return unit_test._replace(
        packages=packages,
        profiles=profiles,
        variables=variables,
        remediation=remediation,
        check=check,
    )


def iter_tests(rule_dir):
    """
    Given a rule directory containing tests, yield tuples of
    (partial UnitTest , test file path) representing tests found in that
    directory.
    """
    rule_dir = Path(rule_dir)
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


def iter_rules(built_tests_dir):
    """
    Given a directory with built tests, yield pathlib.Path directories
    with tests, the names of which should correspond to rule names,
    plus the special directory 'shared'.
    """
    built_tests_dir = Path(built_tests_dir)
    for rule_dir in sorted(Path(built_tests_dir).iterdir(), key=lambda x: x.name):
        # tests are inside rule-named directories, skip non-dir files
        if rule_dir.is_dir():
            yield rule_dir

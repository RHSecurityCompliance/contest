#!/usr/bin/python3
"""
This is a standalone script which processes provided results.txt.gz files
and identifies invalid waivers. The waiver is invalid if it:
 - did not match any test results,
 - or only matched the 'pass' test results.

The identified invalid waivers are printed to the standard output.
"""

import re
import sys
import gzip
import pathlib
import argparse
import textwrap
import collections

# add the parent directory to the sys.path so we can import from the lib directory
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
from lib import waive, versions


MatchedWaiver = collections.namedtuple(
    'MatchedWaiver',
    ['regex', 'python_source'],
)


class _FakeRhel(versions._Rhel):
    @staticmethod
    def is_true_rhel():
        return True  # always assume we're on RHEL

    @staticmethod
    def is_centos():
        return False  # always assume we're on RHEL

    @staticmethod
    def __bool__():
        return True  # always assume we're on RHEL


_sections_cache = None


def unwaive_note(waive_text, note):
    # there are 2 possible types of note containing waive text:
    #  - (waived X)
    #  - ((waived X) some text)
    if note.startswith('(('):
        note = note[1:]
    return note.removeprefix(waive_text).removeprefix(' ').rstrip(')')


def match_result_mark_waiver(regexes_matched_list, version, arch, status, name, note):
    """This function is an updated version of the match_result() function from the lib/waive.py."""
    # make sure "'something' in name" always works
    if name is None:
        name = ''
    if note is None or note == '[]':
        note = ''

    if '(waived fail)' in note:
        note = unwaive_note('(waived fail)', note)
        status = 'fail'
    elif '(waived error)' in note:
        note = unwaive_note('(waived error)', note)
        status = 'error'

    objs = {
        'status': status,
        'name': name,
        'note': note,
        'arch': arch,
        'rhel': _FakeRhel(version),
        'env': '',
        'Match': waive.Match,
    }

    for section in _sections_cache:
        for regex in section.regexes:
            if regex.fullmatch(name):
                ret = eval(section.python_code, objs, None)

                if not isinstance(ret, waive.Match):
                    if not isinstance(ret, bool):
                        raise RuntimeError(
                            f"waiver python code did not return bool or Match: {ret}",
                        )
                    ret = waive.Match(ret)

                if ret:
                    # both regex and python code matched
                    m = MatchedWaiver(regex, section.python_source)
                    if m not in regexes_matched_list:
                        regexes_matched_list.append(m)


def load_and_process_results(file, regexes_matched_list):
    with gzip.open(file, 'rt') as f:
        for line in f:
            line = line.strip()
            version, arch, status, name, note = line.split('\t')

            if version == 'rhel':  # skip the header
                continue
            # do not consider 'pass' test results, even if waivers would match them
            # we still want to remove such waivers
            if status not in ['fail', 'error', 'warn']:
                continue

            match_result_mark_waiver(regexes_matched_list, version, arch, status, name, note)


def get_invalid_waivers(result_file_list):
    # list of MatchedWaiver tuples containing regex that matched 'fail' or 'error'
    # test result and the associated python source code
    regexes_matched_list = []

    global _sections_cache
    _sections_cache = list(waive.collect_waivers())

    for file in result_file_list:
        load_and_process_results(file, regexes_matched_list)

    print(
        "===============================================================\n"
        "The following waivers are no longer valid, they either did not\n"
        "match any test results or only matched the 'pass' test results:\n"
        "===============================================================\n",
    )
    for section in _sections_cache:
        # if "is_centos()" is in section.python_source and there is no "or"
        # logical operator the section is only applicable for centos so skip it
        or_operator_in_py_code = bool(re.search(r'\s+or\s+', section.python_source) is not None)
        centos_section = bool(
            'is_centos()' in section.python_source and not or_operator_in_py_code,
        )
        if centos_section:
            continue

        found_non_matching = False
        for regex in section.regexes:
            if MatchedWaiver(regex, section.python_source) not in regexes_matched_list:
                found_non_matching = True
                print(regex.pattern)
        if found_non_matching:
            print(f"    {section.python_source}\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=textwrap.dedent("""
            Process results.txt.gz files and identify invalid waivers. The waiver is invalid
            if it did not match any test results or only matched the 'pass' test results.

            IMPORTANT: Test results for all RHEL versions need to be provided, otherwise
            this script won't be able to identify the invalid waivers properly.
            """),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "result_file", nargs='+',
        help="The results.txt.gz file with test results to process",
    )
    args = parser.parse_args()
    get_invalid_waivers(args.result_file)

"""
Functionality for an automatic failure waiving logic, configured by
a custom file format. See WAIVERS.md.
"""

import os
import re
import platform
import collections
from pathlib import Path

from lib import util, versions, oscap

WaiverSection = collections.namedtuple(
    'WaiverSection',
    ['regexes', 'python_code', 'python_source'],
)
_sections_cache = None


class _PushbackIterator:
    """
    A simple wrapper for an iterator that allows the user to "push back"
    the last retrieved item, so it appears again in next().
    """
    def __init__(self, source):
        self.it = iter(source)
        self.pushed_back = False
        self.last = None
        self.counter = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.pushed_back:
            self.pushed_back = False
            return self.last
        else:
            new = next(self.it)
            self.last = new
            self.counter += 1
            return new

    def pushback(self):
        self.pushed_back = True


class WaiveParseError(SyntaxError):
    """
    Easy waiver file syntax error reporting, with line numbers derived
    from _PushbackIterator style counter.
    """
    def __init__(self, filedesc, msg):
        file, line = filedesc
        super().__init__(f"waiver {file}:{line}: {msg}")


def _compile_eval(meta, code):
    if not code.strip():
        raise WaiveParseError(meta, "empty python block code ending here")
    try:
        return compile(util.dedent(code), 'waivercode', 'eval')
    except Exception:
        raise WaiveParseError(meta, "compiling waiver python code failed")


def _parse_waiver_file(stream, filename):
    sections = []
    regexes = set()
    python_code = ''
    state = 'skipping_empty_lines'

    lines = _PushbackIterator(stream)
    for line in lines:
        if line.startswith('#'):
            continue
        line = line.rstrip('\n')
        filedesc = (filename, lines.counter)

        # between regex+python blocks
        if state == 'skipping_empty_lines':
            if line:
                # non-empty line found, assume we're at the start of a new
                # regex+python block - start parsing it
                state = 'reading_regex'
                lines.pushback()

        # collecting adjacent/subsequent regex lines
        elif state == 'reading_regex':
            if not line:
                raise WaiveParseError(filedesc, "unexpected empty line between regexes")

            # until we see an indented line (beginning with space), just collect
            # regex lines into a buffer
            if not line.startswith((' ', '\t')):
                try:
                    regexes.add(re.compile(line))
                except re.error as e:
                    raise WaiveParseError(filedesc, f"regex failed: {e}")
            else:
                # indented line found, which means it's a python code - parse it
                if not regexes:
                    raise WaiveParseError(filedesc, "python block without a preceding regexp")
                state = 'reading_python'
                lines.pushback()

        # reading python code related to a set of regex lines
        elif state == 'reading_python':
            if line.startswith((' ', '\t')):
                # indented line - assume it's still python code
                python_code += f'{line}\n'
            else:
                # non-indented line - either empty (between regex+python blocks)
                # or the start of a new regex+python block -- either case, we're
                # done with the current block, so add it to the list & cleanup
                sections.append(
                    WaiverSection(regexes, _compile_eval(lines, python_code), python_code.strip()),
                )
                regexes = set()
                python_code = ''
                state = 'skipping_empty_lines'
                lines.pushback()

    if regexes and not python_code:
        raise WaiveParseError(filedesc, "no python block follows the regexp")

    # still inside last python block - the append & cleanup section did not
    # get to run because the iterator stopped because there was nothing left
    # in the text file after the last python block (not even an empty line),
    # so do the appending here
    if python_code:
        sections.append(
            WaiverSection(regexes, _compile_eval(lines, python_code), python_code.strip()),
        )

    return sections


def collect_waivers():
    """
    Recursively walk a directory of waiver files/directories,
    yielding waiver sections.
    """
    # note: we don't use os.walk() because it splits files and directories
    # into two lists, breaking sorting - we want to treat both equally, so that
    # files can interleave directories in the sorted order
    dir_name = os.environ.get('CONTEST_WAIVER_DIR', 'conf/waivers')
    dir_path = Path(util.libdir).parent / dir_name
    util.log(f"using {dir_path} for waiving")

    def _collect_files(in_dir):
        for item in sorted(in_dir.iterdir()):
            if item.name.startswith('.'):
                continue
            if item.is_dir():
                yield from _collect_files(item)
            elif item.is_file():
                yield item

    for file in _collect_files(dir_path):
        relative = file.relative_to(dir_path)
        with open(file) as f:
            yield from _parse_waiver_file(f, str(relative))


class Match:
    """
    A True/False result with additional metadata, returned from
    custom waiving format and its python code blocks.

    Use 'strict=True' to fail when the waiver matches on 'pass'.
    """
    def __init__(self, matches, *, strict=False, note=None):
        self.matches = matches
        self.strict = strict
        self.note = note

    def __bool__(self):
        return self.matches


def match_result(status, name, note):
    global _sections_cache
    if _sections_cache is None:
        _sections_cache = list(collect_waivers())

    # make sure "'something' in name" always works
    if name is None:
        name = ''
    if note is None:
        note = ''

    if name:
        # prepend test name to a sub-result
        name = util.get_test_name() + f'/{name}'
        subresult = True
    else:
        # use the actual test name, not '/'
        name = util.get_test_name()
        subresult = False

    def _rule_has_no_remediation(remediation_type):
        # if the test name is not provided (None), we are not processing a sub-result with rule
        # name, but the full (absolute) test name of the currently running test as returned
        # by the util.get_test_name() function (e.g. '/hardening/kickstart/stig') and in such
        # cases we want `no_remediation` function to return False
        if not subresult:
            return False
        # extract the rule name from the test name
        # (e.g. '/hardening/kickstart/stig/configure_crypto_policy')
        rule = name.rpartition('/')[2]
        return not oscap.global_ds().has_remediation(rule, remediation_type)

    objs = {
        # result related
        'status': status,
        'name': name,
        'note': note,
        # platform related
        'arch': platform.machine(),
        'rhel': versions.rhel,
        # environmental
        'env': os.environ.get,
        'no_remediation': _rule_has_no_remediation,
        'fix': oscap.FixType,
        # special
        'Match': Match,
    }

    for section in _sections_cache:
        if any(x.fullmatch(name) for x in section.regexes):
            ret = eval(section.python_code, objs, None)

            if not isinstance(ret, Match):
                if not isinstance(ret, bool):
                    raise RuntimeError(f"waiver python code did not return bool or Match: {ret}")
                ret = Match(ret)

            if ret:
                return ret  # both regex and python code matched

    return Match(False)


def rewrite_result(status, name, note, new_status='warn'):
    if os.environ.get('CONTEST_VERBATIM_RESULTS') == '1' or status in ['info', 'skip', 'warn']:
        return (status, name, note)

    matched = match_result(status, name, note)
    if not matched:
        return (status, name, note)

    def add_note(text):
        return f'({text}) {note}' if note else text

    if status == 'pass':
        if matched.strict or os.environ.get('CONTEST_STRICT_WAIVERS') == '1':
            return ('fail', name, add_note("waive: expected fail/error, got pass"))
        else:
            return (status, name, add_note("waived pass"))
    elif status == 'fail':
        # if Match object overrides the note, use it
        if matched.note:
            return (new_status, name, add_note(matched.note))

    # remaining fail or error statuses
    return (new_status, name, add_note(f"waived {status}"))

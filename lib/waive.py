"""
Functionality for an automatic failure waiving logic, configured by
a custom file format. See WAIVERS.md.
"""

import os
import re
import platform
from pathlib import Path

from lib import util, versions

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
    def __init__(self, meta, msg):
        super().__init__(f"waiver line {meta.counter}: {msg}")


def _compile_eval(meta, code):
    if not code.strip():
        raise WaiveParseError(meta, "empty python block code ending here")
    try:
        return compile(util.dedent(code), 'waivercode', 'eval')
    except Exception:
        raise WaiveParseError(meta, "compiling waiver python code failed")


def _parse_waiver_file(stream):
    sections = []
    regexes = set()
    python_code = ''
    state = 'skipping_empty_lines'

    lines = _PushbackIterator(stream)
    for line in lines:
        if line.startswith('#'):
            continue
        line = line.rstrip('\n')

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
                raise WaiveParseError(lines, "unexpected empty line between regexes")

            # until we see an indented line (beginning with space), just collect
            # regex lines into a buffer
            if not line.startswith((' ', '\t')):
                try:
                    regexes.add(re.compile(line))
                except re.error as e:
                    raise WaiveParseError(lines, f"regex failed: {e}")
            else:
                # indented line found, which means it's a python code - parse it
                if not regexes:
                    raise WaiveParseError(lines, "python block without a preceding regexp")
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
                sections.append((regexes, _compile_eval(lines, python_code)))
                regexes = set()
                python_code = ''
                state = 'skipping_empty_lines'
                lines.pushback()

    if regexes and not python_code:
        raise WaiveParseError(lines, "no python block follows the regexp")

    # still inside last python block - the append & cleanup section did not
    # get to run because the iterator stopped because there was nothing left
    # in the text file after the last python block (not even an empty line),
    # so do the appending here
    if python_code:
        sections.append((regexes, _compile_eval(lines, python_code)))

    return sections


def _open_waiver_file():
    preferred = os.environ.get('CONTEST_WAIVERS', 'released')
    waiver_file = Path(util.libdir).parent / 'conf' / f'waivers-{preferred}'
    if not waiver_file.exists():
        raise FileNotFoundError(f"{waiver_file.name} doesn't exist in 'conf'")
    util.log(f"using {waiver_file} for waiving")
    return open(waiver_file)


class Match:
    """
    A True/False result with additional metadata, returned from
    custom waiving format and its python code blocks.
    """
    def __init__(self, matches, *, sometimes=False):
        self.matches = matches
        self.sometimes = sometimes

    def __bool__(self):
        return self.matches


def match_result(status, name, note):
    global _sections_cache
    if _sections_cache is None:
        with _open_waiver_file() as f:
            _sections_cache = _parse_waiver_file(f)

    # make sure "'someting' in name" always works
    if name is None:
        name = ''
    if note is None:
        note = ''

    if name:
        # prepend test name to a sub-result
        name = util.get_test_name() + f'/{name}'
    else:
        # use the actual test name, not '/'
        name = util.get_test_name()

    objs = {
        # result related
        'status': status,
        'name': name,
        'note': note,
        # platform related
        'arch': platform.machine(),
        'rhel': versions.rhel,
        'oscap': versions.oscap,
        # environmental
        'env': os.environ.get,
        # special
        'Match': Match,
    }

    for section in _sections_cache:
        regexes, python_code = section

        if any(x.fullmatch(name) for x in regexes):
            ret = eval(python_code, objs, None)

            if not isinstance(ret, Match):
                if not isinstance(ret, bool):
                    raise RuntimeError(f"waiver python code did not return bool or Match: {ret}")
                ret = Match(ret)

            if ret:
                return ret  # both regex and python code matched

    return Match(False)


def rewrite_result(status, name, note, new_status='warn'):
    if status in ['info', 'warn']:
        return (status, name, note)

    matched = match_result(status, name, note)
    if not matched:
        return (status, name, note)

    def add_note(text):
        return f'({text}) {note}' if note else text

    if status == 'pass':
        if matched.sometimes:
            return (status, name, add_note(f"waived {status}"))
        else:
            return ('error', name, add_note("waive: expected fail/error, got pass"))

    # fail or error
    return (new_status, name, add_note(f"waived {status}"))

import sys
import re
import contextlib
from pathlib import Path

from . import util, results

_no_remediation_cache = None


def _rules_without_remediation():
    # TODO: parse this info from datastream XML
    cmd = ['oscap', 'xccdf', 'generate', '--profile', '(all)', 'fix', util.get_datastream()]
    _, lines = util.subprocess_stream(cmd, check=True)
    for line in lines:
        match = re.search('FIX FOR THIS RULE \'xccdf_org.ssgproject.content_rule_(.+)\' IS MISSING!', line)  # noqa
        if match:
            yield match.group(1)


def has_no_remediation(rule):
    global _no_remediation_cache
    if _no_remediation_cache is None:
        _no_remediation_cache = set(_rules_without_remediation())
    return rule in _no_remediation_cache


def rule_from_verbose(line):
    """
    Get (rulename, status) from an oscap info verbose output line.

    Return None if the input line is not a valid oscap verbose result line.
    """
    match = re.match(r'^xccdf_org.ssgproject.content_rule_(.+):([a-z]+)$', line)
    if match:
        return (match.group(1), match.group(2))
    else:
        return None


def rules_from_verbose(lines):
    """
    Yield (rulename, status, verboselog) from oscap info verbose output.

    Note that this expects 'oscap xccdf eval' to be run:
      - with --verbose INFO
      - with --progress
      - with stdout and stderr merged, ie. 2>&1

    If running with openscap < 1.3, this function expects oscap to be run:
      - without any --verbose (uses different format)
      - with --progress
      - without any redirect (due to broken locking), keeping stdout clean
    """
    log = ''
    for line in lines:
        # oscap xccdf eval --progress rule name and status
        match = rule_from_verbose(line)
        if match:
            sys.stdout.write(f'{line}\n')
            sys.stdout.flush()
            rulename, status = match
            yield (rulename, status, log)
            log = ''
            continue

        # print out any unrelated warnings/errors
        if not line.startswith('I: oscap: '):
            sys.stdout.write(f'{line}\n')
            sys.stdout.flush()
            continue

        # insides of an existing rule block
        # (.removeprefix() is python 3.9+)
        log += f'{line[10:]}\n'


def report_from_verbose(lines):
    """
    Report results from oscap output.
    See rules_from_verbose() for requirements on the output.
    """
    total = 0

    for rule, status, verbose_out in rules_from_verbose(lines):
        total += 1
        note = None

        if status in ['pass', 'error']:
            pass
        elif status in ['notapplicable', 'notchecked', 'notselected', 'informational']:
            note = status
            status = 'info'
        else:
            note = status
            status = 'error'

        if verbose_out:
            logfile = 'oscap.log.txt'  # txt to make browsers open it natively
            Path(logfile).write_text(verbose_out)
            results.report(status, rule, note, [logfile])
        else:
            results.report(status, rule, note)

    if total == 0:
        raise RuntimeError("oscap returned no results")

    util.log(f"all done: {total} total results")


@contextlib.contextmanager
def unselect_rules(orig_ds, new_ds, rules):
    """
    Given
    - a source XML file path as 'orig_ds',
    - a destination XML file path as 'new_ds',
    - an iterable of rules (partial or full rule names),
    copy the source datastream to the destination one, disabling the
    specified rules.
    """
    prefix = 'xccdf_org.ssgproject.content_rule_'
    rules = (x if x.startswith(prefix) else prefix + x for x in rules)

    exprs = set()
    for rule in rules:
        exprs.add(re.compile(fr'<.*Rule.*id="{rule}'))
        exprs.add(re.compile(fr'<.*select.*idref="{rule}'))

    new_ds = Path(new_ds)
    # remove a possible existing/old file
    if new_ds.exists():
        new_ds.unlink()

    with open(orig_ds) as orig_ds_f:
        with open(new_ds, 'w') as new_ds_f:
            for line in orig_ds_f:
                if any(x.search(line) for x in exprs):
                    line = line.replace('selected="true"', 'selected="false"')
                    util.log(f'unselected {line.strip()}')
                new_ds_f.write(line)

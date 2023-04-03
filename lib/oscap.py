import sys
import re
import logging
import subprocess
from pathlib import Path

import tmt
import util
from versions import rhel

_log = logging.getLogger(__name__).debug

datastream = f'/usr/share/xml/scap/ssg/content/ssg-rhel{rhel.major}-ds.xml'


# TODO: query this from a locally-installed scap-security-guide instead of a guest?
#def _rules_with_remediation(guest):
#    cmd = f'oscap xccdf generate --profile "(all)" fix {datastream} | grep "^# BEGIN fix ("'
#    out = guest.ssh(cmd, capture=True)
#    out.check_returncode()
#    for i in out.stdout.decode().strip().split('\n'):
#        yield re.sub('^# BEGIN fix .*\) for \'xccdf_org.ssgproject.content_rule_(.*)\'$', r'\1', i)
#
# TODO: run without shell=True, 'grep' natively in python
def _rules_without_remediation():
    #cmd = f'oscap xccdf generate --profile "(all)" fix {datastream} | grep "^# BEGIN fix ("'
    cmd = ['oscap', 'xccdf', 'generate', '--profile', '(all)', 'fix', datastream]
    proc, lines = util.proc_stream(cmd, check=True)
    for line in lines:
        match = re.search('FIX FOR THIS RULE \'xccdf_org.ssgproject.content_rule_(.+)\' IS MISSING!', line)
        if match:
            yield match.group(1)


_no_remediation_cache = None
def has_no_remediation(rule):
    global _no_remediation_cache
    if _no_remediation_cache is None:
        _no_remediation_cache = set(_rules_without_remediation())
    return rule in _no_remediation_cache


def rules_from_verbose(lines):
    """
    Get (rulename, result, verboselog) from oscap info verbose output.

    Note that this expects 'oscap xccdf eval' to be run:
      - with --verbose INFO
      - with --progress
      - with stdout and stderr merged, ie. 2>&1
    """
    log = ''
    for line in lines:
        # oscap xccdf eval --progress rule name and result
        match = re.match(f"^xccdf_org.ssgproject.content_rule_(.+):([a-z]+)$", line)
        if match:
            yield (match.group(1), match.group(2), log)
            log = ''
            continue

        # print out any unrelated warnings/errors
        if not line.startswith('I: oscap: '):
            sys.stdout.write(line)
            sys.stdout.flush()
            continue

        # insides of an existing rule block
        # (.removeprefix() is python 3.9+)
        log += f'{line[10:]}\n'


def report_from_verbose(lines):
    """
    Report tmt results from oscap output.
    See rules_from_verbose() for requirements on the output.
    """
    for rule, result, details in rules_from_verbose(lines):
        note = None
        logfile = None

        if details:
            logfile = 'oscap.log.txt'  # txt to make browsers open it natively
            Path(logfile).write_text(details)

        if result in ['pass', 'error']:
            pass  # same as tmt
        elif result == 'fail':
            if has_no_remediation(rule):
                note = 'no remediation'
                result = 'warn'
        elif result in ['notapplicable', 'notchecked', 'notselected', 'informational']:
            note = result
            result = 'info'
        else:
            note = result
            result = 'error'

        tmt.report(result, f'/{rule}', note, [logfile])


#def rules_from_progress(lines):
#    """
#    Get (rulename, result) from oscap xccdf eval --progress output.
#
#    On RHEL-8 and newer, use rules_from_verbose instead.
#    """
#    for line in lines:
#        match = re.match(f"^(xccdf_org.ssgproject.content_rule_.+):([a-z]+)$", line)
#        if match:
#            yield (match.group(1), match.group(2))
#        else:
#            sys.stdout.write(line)
#            sys.stdout.flush()






# TODO: rules_from_verbose only on newer oscap version,
#       old one doesn't have oscap --verbose, only oscap xccdf eval --verbose,
#       which has a different implementation and broken (interleaved) output
#       with stdout and rule name printing

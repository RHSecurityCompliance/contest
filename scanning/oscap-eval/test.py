#!/usr/bin/python3

import sys
import re
import subprocess

from lib import util, results, oscap


got_normal_result = False

# remember and avoid reporting freeform errors/warnings more than once
problems_seen = set()

proc, lines = util.subprocess_stream(
    ['oscap', 'xccdf', 'eval', '--profile', '(all)', '--progress', util.get_datastream()],
    stderr=subprocess.STDOUT)

for line in lines:
    sys.stdout.write(f'{line}\n')
    sys.stdout.flush()

    # valid results, of error/unknown status
    match = oscap.rule_from_verbose(line)
    if match:
        rulename, status = match
        if status in ['error', 'unknown']:
            results.report('fail', rulename, f'scanner returned: {status}')
        else:
            got_normal_result = True

    # random spurious ERRORs / WARNINGs
    elif line.startswith(('E: ', 'ERROR: ')):
        line = re.sub(' +', ' ', line)
        if line not in problems_seen:
            results.report('fail', 'ERROR', line)
            problems_seen.add(line)

    elif line.startswith(('W: ', 'WARNING: ')):
        line = re.sub(' +', ' ', line)
        if line not in problems_seen:
            results.report('warn', 'WARNING', line)
            problems_seen.add(line)

if proc.returncode not in [0,2]:
    raise RuntimeError("oscap failed unexpectedly")

if not got_normal_result:
    raise RuntimeError("oscap returned no valid results")

results.report_and_exit()

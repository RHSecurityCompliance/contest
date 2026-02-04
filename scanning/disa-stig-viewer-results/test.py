#!/usr/bin/python3

import re
import subprocess

from lib import util, results

proc = util.subprocess_run(
    ['oscap', 'xccdf', 'eval', '--profile', 'stig', '--progress',
     '--stig-viewer', 'stig_results.xml', util.get_datastream()],
    stderr=subprocess.STDOUT)
if proc.returncode not in [0,2]:
    raise RuntimeError("oscap failed unexpectedly")
results.add_log('stig_results.xml')

# parse stig_results.xml and count STIG results
with open('stig_results.xml') as f:
    stig_content = f.read()
stig_results_count = len(re.findall(r'<rule-result\s+idref="SV-', stig_content))

note = f'number of rules with STIG Viewer reference: {stig_results_count}'
if stig_results_count > 0:
    results.report_and_exit('pass', note=note)
else:
    results.report_and_exit('fail', note=note)

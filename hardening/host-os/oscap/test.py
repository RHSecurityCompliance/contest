#!/usr/bin/python3

import os
import subprocess

from pathlib import Path

from lib import util, results, oscap, versions
from conf import remediation_excludes


profile = os.environ['PROFILE']
profile = f'xccdf_org.ssgproject.content_profile_{profile}'

ds = util.get_datastream()

unique_name = util.get_test_name().lstrip('/').replace('/', '-')
new_ds = Path(f'/var/tmp/contest-{unique_name}')

if util.get_reboot_count() == 0:

    util.log("first boot, doing remediation")
    oscap.unselect_rules(ds, new_ds, remediation_excludes.host_os)
    proc = util.subprocess_run(
        ['oscap', 'xccdf', 'eval', '--profile', profile,
         '--progress', '--remediate', new_ds])
    if proc.returncode not in [0,2]:
        raise RuntimeError("remediation oscap failed unexpectedly")

    # restore basic login functionality
    util.subprocess_run(['chage', '-d', '99999', 'root'], check=True)
    with open('/etc/sysconfig/sshd', 'a') as f:
        f.write('\nOPTIONS=-oPermitRootLogin=yes\n')

    util.reboot()

else:

    util.log("second boot, scanning")

    # old RHEL-7 oscap mixes errors into --progress rule names without a newline
    verbose = ['--verbose', 'INFO'] if versions.oscap >= 1.3 else []
    redir = {'stderr': subprocess.STDOUT} if versions.oscap >= 1.3 else {}

    # scan the remediated system
    proc, lines = util.subprocess_stream(
        ['oscap', 'xccdf', 'eval', *verbose, '--profile', profile,
         '--progress', '--report', 'report.html', new_ds], **redir)
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    results.report_and_exit(logs=['report.html'])

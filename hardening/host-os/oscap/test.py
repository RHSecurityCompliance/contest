#!/usr/bin/python3

import os
import subprocess
import shutil

from pathlib import Path

from lib import util, results, oscap, versions
from conf import remediation


profile = os.environ['PROFILE']
profile = f'xccdf_org.ssgproject.content_profile_{profile}'

ds = util.get_datastream()

unique_name = util.get_test_name().lstrip('/').replace('/', '-')

# persistent across reboots
tmpdir = Path(f'/var/tmp/contest-{unique_name}')
new_ds = tmpdir / 'modified_datastream.xml'

if util.get_reboot_count() == 0:
    util.log("first boot, doing remediation")

    if tmpdir.exists():
        shutil.rmtree(tmpdir)
    tmpdir.mkdir()

    oscap.unselect_rules(ds, new_ds, remediation.excludes())
    cmd = [
        'oscap', 'xccdf', 'eval', '--profile', profile,
        '--progress', '--remediate', '--report', tmpdir / 'remediation.html',
        new_ds,
    ]
    proc = util.subprocess_run(cmd)
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
    # RHEL-7 HTML report doesn't contain OVAL findings by default
    oval_results = [] if versions.oscap >= 1.3 else ['--results', 'results.xml', '--oval-results']

    # scan the remediated system
    cmd = [
        'oscap', 'xccdf', 'eval', *verbose, '--profile', profile,
        '--progress', '--report', 'report.html', *oval_results,
        new_ds,
    ]
    proc, lines = util.subprocess_stream(cmd, **redir)
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    results.report_and_exit(logs=['report.html', tmpdir / 'remediation.html'])

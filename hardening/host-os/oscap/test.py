#!/usr/bin/python3

import shutil

from pathlib import Path

from lib import util, results, oscap
from conf import remediation


profile = util.get_test_name().rpartition('/')[2]
profile = f'xccdf_org.ssgproject.content_profile_{profile}'

unique_name = util.get_test_name().lstrip('/').replace('/', '-')

# persistent across reboots
tmpdir = Path(f'/var/tmp/contest-{unique_name}')
remediation_ds = tmpdir / 'remediation-ds.xml'


def do_one_remediation(ds, profile, html_report):
    cmd = [
        'oscap', 'xccdf', 'eval', '--profile', profile, '--progress',
        '--report', html_report, '--remediate', ds,
    ]
    proc = util.subprocess_run(cmd)
    if proc.returncode not in [0,2]:
        raise RuntimeError(f"remediation oscap failed with {proc.returncode}")
    # restore basic login functionality
    cfg_path = Path('/etc/sysconfig/sshd')
    if 'OPTIONS=-oPermitRootLogin=yes' not in cfg_path.read_text():
        with cfg_path.open('a') as f:
            f.write('\nOPTIONS=-oPermitRootLogin=yes\n')


if util.get_reboot_count() == 0:
    util.log("first boot, doing remediation")

    if tmpdir.exists():
        shutil.rmtree(tmpdir)
    tmpdir.mkdir()

    oscap.unselect_rules(util.get_datastream(), remediation_ds, remediation.excludes())

    do_one_remediation(remediation_ds, profile, tmpdir / 'remediation.html')

    util.reboot()

# remediate twice due to some rules being 'notapplicable'
# on the first pass
elif util.get_reboot_count() == 1:
    util.log("second boot, doing second remediation")

    do_one_remediation(remediation_ds, profile, tmpdir / 'remediation2.html')

    util.reboot()

else:
    util.log("third boot, scanning")

    # scan the remediated system
    # - use the original unmodified datastream
    cmd = [
        'oscap', 'xccdf', 'eval', '--profile', profile, '--progress',
        '--report', 'report.html', '--results-arf', 'results-arf.xml',
        util.get_datastream(),
    ]
    proc, lines = util.subprocess_stream(cmd)
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    util.subprocess_run(['gzip', '-9', 'results-arf.xml'], check=True)

    logs = [
        'report.html',
        'results-arf.xml.gz',
        tmpdir / 'remediation.html',
        tmpdir / 'remediation2.html',
    ]
    results.report_and_exit(logs=logs)

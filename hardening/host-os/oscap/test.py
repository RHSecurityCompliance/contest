#!/usr/bin/python3

import shutil

from pathlib import Path

from lib import util, results, oscap
from conf import remediation


profile = util.get_test_name().rpartition('/')[2]

unique_name = util.get_test_name().lstrip('/').replace('/', '-')

# persistent across reboots
tmpdir = Path(f'/var/tmp/contest-{unique_name}')
remediation_ds = tmpdir / 'remediation-ds.xml'


def do_one_remediation(ds, profile, arf_results):
    cmd = [
        'oscap', 'xccdf', 'eval', '--profile', profile, '--progress',
        '--results-arf', arf_results, '--remediate', ds,
    ]
    proc = util.subprocess_run(cmd)
    if proc.returncode not in [0,2]:
        raise RuntimeError(f"remediation oscap failed with {proc.returncode}")


if util.get_reboot_count() == 0:
    util.log("first boot, doing remediation")

    if tmpdir.exists():
        shutil.rmtree(tmpdir)
    tmpdir.mkdir()

    oscap.unselect_rules(util.get_datastream(), remediation_ds, remediation.excludes())

    do_one_remediation(remediation_ds, profile, tmpdir / 'remediation-arf.xml')

    util.reboot()

# remediate twice due to some rules being 'notapplicable'
# on the first pass
elif util.get_reboot_count() == 1:
    util.log("second boot, doing second remediation")

    do_one_remediation(remediation_ds, profile, tmpdir / 'remediation2-arf.xml')

    util.reboot()

else:
    util.log("third boot, scanning")

    # scan the remediated system
    # - use the original unmodified datastream
    cmd = [
        'oscap', 'xccdf', 'eval', '--profile', profile, '--progress',
        '--report', 'report.html', '--results-arf', 'scan-arf.xml',
        util.get_datastream(),
    ]
    proc, lines = util.subprocess_stream(cmd)
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    # TODO: str() because of python 3.6 shutil.move() not supporting Path
    shutil.move(str(tmpdir / 'remediation-arf.xml'), '.')
    shutil.move(str(tmpdir / 'remediation2-arf.xml'), '.')

    tar = [
        'tar', '-cvJf', 'results-arf.tar.xz',
        'remediation-arf.xml', 'remediation2-arf.xml', 'scan-arf.xml',
    ]
    util.subprocess_run(tar, check=True)

    logs = [
        'report.html',
        'results-arf.tar.xz',
    ]
    results.report_and_exit(logs=logs)

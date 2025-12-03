#!/usr/bin/python3

import shutil
import subprocess
from pathlib import Path

from lib import results, oscap, osbuild, util, metadata, versions
from conf import remediation


# try to prevent the following error (usually happens on new RHEL versions in development):
# ERROR: BlueprintsError: contest_blueprint: GetDistro - unknown distribution rhel-X.Y
# which is caused by the absence of rhel-X.Y.json in /usr/share/osbuild-composer/repositories;
# if /usr/share/osbuild-composer/repositories/rhel-X.Y.json does not exist, we try to create it
# by copying rhel-X.json if it exists
repos_dir = Path('/usr/share/osbuild-composer/repositories')
rhel_xy_json = repos_dir / f'rhel-{versions.rhel.major}.{versions.rhel.minor}.json'
rhel_x_json = repos_dir / f'rhel-{versions.rhel.major}.json'
if not rhel_xy_json.exists() and rhel_x_json.exists():
    util.log(f"{rhel_xy_json} does not exist, creating it by copying {rhel_x_json}")
    shutil.copy(rhel_x_json, rhel_xy_json)

osbuild.Host.setup()

g = osbuild.Guest()

profile = util.get_test_name().rpartition('/')[2]

oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())

# provide our modified DS via RpmPack to the VM as /root/remediation-ds.xml,
# tell the 'oscap xccdf eval --remediate' called by osbuild-composer to use it
rpmpack = util.RpmPack()
rpmpack.add_file('remediation-ds.xml', '/root/remediation-ds.xml')

cmd = [
    'oscap', 'xccdf', 'generate', '--profile', profile,
    'fix', '--fix-type', 'blueprint',
    'remediation-ds.xml',
]
_, lines = util.subprocess_stream(cmd, check=True, stderr=subprocess.PIPE)
blueprint = osbuild.translate_oscap_blueprint(lines, '/root/remediation-ds.xml')

g.create(blueprint=blueprint, rpmpack=rpmpack, secure_boot=('uefi' in metadata.tags()))

with g.booted():
    # copy the original DS to the guest
    g.copy_to(util.get_datastream(), 'scan-ds.xml')
    # scan the remediated system
    proc, lines = g.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf scan-arf.xml scan-ds.xml',
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError(f"post-reboot oscap failed unexpectedly with {proc.returncode}")

    g.copy_from('report.html')
    g.copy_from('scan-arf.xml')

results.report_and_exit(logs=['report.html', 'scan-arf.xml', g.osbuild_log])

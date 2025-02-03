#!/usr/bin/python3

import os

from lib import util, results, virt, oscap
from conf import remediation, partitions


virt.Host.setup()

_, variant, profile = util.get_test_name().rsplit('/', 2)
with_fips = os.environ.get('WITH_FIPS') == '1'

if variant == 'with-gui':
    guest_tag = 'gui_with_oscap'
elif variant == 'uefi':
    guest_tag = 'uefi_with_oscap'
else:
    guest_tag = 'minimal_with_oscap'

if with_fips:
    guest_tag += '_fips'

g = virt.Guest(guest_tag)

if not g.can_be_snapshotted():
    ks = virt.Kickstart(partitions=partitions.partitions)
    if variant == 'with-gui':
        ks.packages.append('@Server with GUI')
    g.install(
        kickstart=ks,
        secure_boot=(variant == 'uefi'),
        kernel_args=['fips=1'] if with_fips else None,
    )
    g.prepare_for_snapshot()

with g.snapshotted():
    # copy our datastream to the guest
    oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())
    g.copy_to('remediation-ds.xml')

    # - remediate twice due to some rules being 'notapplicable'
    #   on the first pass
    for arf_results in ['remediation-arf.xml', 'remediation2-arf.xml']:
        cmd = [
            'oscap', 'xccdf', 'eval', '--profile', profile,
            '--progress', '--results-arf', arf_results,
            '--remediate', 'remediation-ds.xml',
        ]
        proc = g.ssh(' '.join(cmd))
        if proc.returncode not in [0,2]:
            raise RuntimeError(f"remediation oscap failed with {proc.returncode}")
        g.soft_reboot()

    # copy the original DS to the guest
    g.copy_to(util.get_datastream(), 'scan-ds.xml')
    # scan the remediated system
    proc, lines = g.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf scan-arf.xml scan-ds.xml'
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')
    g.copy_from('remediation-arf.xml')
    g.copy_from('remediation2-arf.xml')
    g.copy_from('scan-arf.xml')

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

#!/usr/bin/python3

import atexit

from lib import util, results, virt, oscap, metadata
from conf import remediation, partitions


virt.Host.setup()

profile = util.get_test_name().rpartition('/')[2]

guest_tag = virt.calculate_guest_tag(metadata.tags())
g = virt.Guest(guest_tag)

if not g.is_installed():
    ks = virt.Kickstart(partitions=partitions.partitions)
    if 'with-gui' in metadata.tags():
        ks.packages.append('@Server with GUI')
    g.install(
        kickstart=ks,
        secure_boot=('uefi' in metadata.tags()),
        kernel_args=['fips=1'] if 'fips' in metadata.tags() else None,
    )

g.prepare_for_snapshot()
atexit.register(g.cleanup_snapshot)

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
        g.copy_from(arf_results)
        results.add_log(arf_results)
        g.soft_reboot()

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

results.report_and_exit(logs=['report.html', 'scan-arf.xml'])

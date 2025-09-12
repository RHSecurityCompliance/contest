#!/usr/bin/python3

import atexit

import shared
from lib import util, results, virt, oscap, versions, metadata
from conf import partitions, remediation


virt.Host.setup()

guest_tag = virt.calculate_guest_tag(metadata.tags())
g = virt.Guest(guest_tag)

if not g.is_installed():
    ks = virt.Kickstart(partitions=partitions.partitions)
    g.install(kickstart=ks, kernel_args=['fips=1'])

g.prepare_for_snapshot()
atexit.register(g.cleanup_snapshot)

with g.snapshotted():
    oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())
    g.copy_to('remediation-ds.xml')
    for _ in range(2):
        cmd = [
            'oscap', 'xccdf', 'eval', '--profile', shared.profile,
            '--progress', '--remediate', 'remediation-ds.xml',
        ]
        proc = g.ssh(' '. join(cmd))
        if proc.returncode not in [0,2]:
            raise RuntimeError(f"remediation oscap failed with {proc.returncode}")
        g.soft_reboot()

    with util.get_source_content() as content_dir:
        g.copy_to(util.get_datastream(), 'ssg-ds.xml')
        shared.content_scan(g, 'ssg-ds.xml', html='ssg-report.html', arf='ssg-arf.xml')
        g.copy_from('ssg-report.html')
        g.copy_from('ssg-arf.xml')

        # There is always one (the latest) DISA benchmark in content src
        references = content_dir / 'shared' / 'references'
        disa_ds = next(
            references.glob(f'disa-stig-rhel{versions.rhel.major}-*-xccdf-scap.xml'),
        )
        g.copy_to(disa_ds, 'disa-ds.xml')
        shared.disa_scan(g, 'disa-ds.xml', html='disa-report.html', arf='disa-arf.xml')
        g.copy_from('disa-report.html')
        g.copy_from('disa-arf.xml')

        # Compare ARFs and report results from output
        shared.compare_arfs('ssg-arf.xml', 'disa-arf.xml')

results.report_and_exit(logs=['ssg-report.html', 'disa-report.html'])

#!/usr/bin/python3

import os

from lib import util, results, virt, oscap
from conf import remediation, partitions


virt.Host.setup()

profile = util.get_test_name().rpartition('/')[2]
profile = f'xccdf_org.ssgproject.content_profile_{profile}'

use_gui = os.environ.get('USE_SERVER_WITH_GUI')

if use_gui:
    g = virt.Guest('gui_with_oscap')
else:
    g = virt.Guest('minimal_with_oscap')

if not g.can_be_snapshotted():
    ks = virt.Kickstart(partitions=partitions.partitions)
    if use_gui:
        ks.add_package_group('Server with GUI')
    g.install(kickstart=ks)
    g.prepare_for_snapshot()

with g.snapshotted():
    # copy our datastream to the guest
    oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())
    g.copy_to('remediation-ds.xml')

    # - remediate twice due to some rules being 'notapplicable'
    #   on the first pass
    for html_report in ['remediation.html', 'remediation2.html']:
        cmd = [
            'oscap', 'xccdf', 'eval', '--profile', profile,
            '--progress', '--report', html_report,
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
        f' --results-arf results-arf.xml scan-ds.xml'
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')
    g.copy_from('results-arf.xml')
    g.copy_from('remediation.html')
    g.copy_from('remediation2.html')

util.subprocess_run(['gzip', '-9', 'results-arf.xml'], check=True)

logs = [
    'report.html',
    'results-arf.xml.gz',
    'remediation.html',
    'remediation2.html',
]
results.report_and_exit(logs=logs)

#!/usr/bin/python3

from lib import util, results, virt, oscap
from conf import remediation, partitions


virt.Host.setup()

profile = util.get_test_name().rpartition('/')[2]

g = virt.Guest('minimal_with_oscap')

if not g.can_be_snapshotted():
    ks = virt.Kickstart(partitions=partitions.partitions)
    g.install(kickstart=ks)
    g.prepare_for_snapshot()

with g.snapshotted(), util.get_old_datastream() as old_xml:
    # copy old and new datastreams to the guest
    oscap.unselect_rules(old_xml, 'remediation-old.xml', remediation.excludes())
    g.copy_to('remediation-old.xml')
    oscap.unselect_rules(util.get_datastream(), 'remediation-new.xml', remediation.excludes())
    g.copy_to('remediation-new.xml')

    def remediate(datastream, html_report, html_report2):
        # remediate twice due to some rules being 'notapplicable'
        # on the first pass
        for html_report in [html_report, html_report2]:
            cmd = [
                'oscap', 'xccdf', 'eval', '--profile', profile,
                '--progress', '--report', html_report,
                '--remediate', datastream,
            ]
            proc = g.ssh(' '.join(cmd))
            if proc.returncode not in [0,2]:
                raise RuntimeError(f"remediation oscap failed with {proc.returncode}")
            g.soft_reboot()

    # remediate using old content,
    # then remediate using new content
    remediate('remediation-old.xml', 'remediation-old.html', 'remediation-old2.html')
    remediate('remediation-new.xml', 'remediation-new.html', 'remediation-new2.html')

    # scan using new content
    g.copy_to(util.get_datastream(), 'scan-new.xml')
    proc, lines = g.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf results-arf.xml scan-new.xml'
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')
    g.copy_from('results-arf.xml')
    g.copy_from('remediation-old.html')
    g.copy_from('remediation-old2.html')
    g.copy_from('remediation-new.html')
    g.copy_from('remediation-new2.html')

util.subprocess_run(['gzip', '-9', 'results-arf.xml'], check=True)

logs = [
    'report.html',
    'results-arf.xml.gz',
    'remediation-old.html',
    'remediation-old2.html',
    'remediation-new.html',
    'remediation-new2.html',
]
results.report_and_exit(logs=logs)

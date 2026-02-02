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
    g.install(
        kickstart=ks,
        kernel_args=['fips=1'] if 'fips' in metadata.tags() else None,
    )

g.prepare_for_snapshot()
atexit.register(g.cleanup_snapshot)

# unselect unwanted rules
with util.get_old_datastream() as old_xml:
    oscap.unselect_rules(old_xml, 'remediation-old.xml', remediation.excludes())
oscap.unselect_rules(util.get_datastream(), 'remediation-new.xml', remediation.excludes())

# check whether the profile is in both old and new
if profile not in oscap.Datastream('remediation-old.xml').profiles:
    results.report_and_exit('skip', "profile missing the old DS")
if profile not in oscap.Datastream('remediation-new.xml').profiles:
    results.report_and_exit('skip', "profile missing the new DS")

with g.snapshotted():
    # copy old and new datastreams to the guest
    g.copy_to('remediation-old.xml')
    g.copy_to('remediation-new.xml')

    def remediate(datastream, arf_results, arf_results2):
        # remediate twice due to some rules being 'notapplicable'
        # on the first pass
        for arf_output in [arf_results, arf_results2]:
            cmd = [
                'oscap', 'xccdf', 'eval', '--profile', profile,
                '--progress', '--results-arf', arf_output,
                '--remediate', datastream,
            ]
            proc = g.ssh(' '.join(cmd))
            if proc.returncode not in [0,2]:
                raise RuntimeError(f"remediation oscap failed with {proc.returncode}")
            g.copy_from(arf_output)
            results.add_log(arf_output)
            g.soft_reboot()

    # remediate using old content,
    # then remediate using new content
    remediate('remediation-old.xml', 'remediation-arf-old.xml', 'remediation-arf-old2.xml')
    remediate('remediation-new.xml', 'remediation-arf-new.xml', 'remediation-arf-new2.xml')

    # scan using new content (without any modifications)
    g.copy_to(util.get_datastream(), 'scan-new.xml')
    proc, lines = g.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf scan-arf.xml scan-new.xml',
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError(f"post-reboot oscap failed unexpectedly with {proc.returncode}")

    g.copy_from('report.html')
    g.copy_from('scan-arf.xml')

results.report_and_exit(logs=['report.html', 'scan-arf.xml'])

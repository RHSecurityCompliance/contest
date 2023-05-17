#!/usr/bin/python3

import os

from lib import util, results, virt, oscap, versions


virt.setup_host()

profile = os.environ['PROFILE']
profile = f'xccdf_org.ssgproject.content_profile_{profile}'

if profile.endswith('_gui'):
    g = virt.Guest('gui_with_oscap')
else:
    g = virt.Guest('minimal_with_oscap')

if not g.can_be_snapshotted():
    ks = virt.Kickstart()
    if profile.endswith('_gui'):
        ks.add_package_group('Server with GUI')
    g.install(kickstart=ks)
    g.prepare_for_snapshot()

with g.snapshotted():
    # copy our datastream to the guest
    g.copy_to(util.get_datastream(), 'contest-ds.xml')

    # remediate, reboot
    g.ssh(f'oscap xccdf eval --profile {profile} --progress --remediate contest-ds.xml')
    g.soft_reboot()

    # old RHEL-7 oscap mixes errors into --progress rule names without a newline
    verbose = '--verbose INFO' if versions.oscap >= 1.3 else ''
    redir = '2>&1' if versions.oscap >= 1.3 else ''

    # scan the remediated system
    proc, lines = g.ssh_stream(f'oscap xccdf eval {verbose} --profile {profile} --progress '
                               f'--report report.html contest-ds.xml {redir}')
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')

results.report_and_exit(logs=['report.html'])

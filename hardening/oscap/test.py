#!/usr/bin/python3

import os

from lib import util, results, virt, oscap, versions
from conf import partitions


virt.Host.setup()

profile = os.environ['PROFILE']
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
    g.copy_to(util.get_datastream(), 'contest-ds.xml')

    # remediate, reboot
    g.ssh(f'oscap xccdf eval --profile {profile} --progress '
          '--report remediation.html --remediate contest-ds.xml')
    g.soft_reboot()

    # old RHEL-7 oscap mixes errors into --progress rule names without a newline
    verbose = '--verbose INFO' if versions.oscap >= 1.3 else ''
    redir = '2>&1' if versions.oscap >= 1.3 else ''
    # RHEL-7 HTML report doesn't contain OVAL findings by default
    oval_results = '' if versions.oscap >= 1.3 else '--results results.xml --oval-results'

    # scan the remediated system
    proc, lines = g.ssh_stream(f'oscap xccdf eval {verbose} --profile {profile} --progress '
                               f'--report report.html {oval_results} contest-ds.xml {redir}')
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')
    g.copy_from('remediation.html')

results.report_and_exit(logs=['report.html', 'remediation.html'])

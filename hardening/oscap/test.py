#!/usr/bin/python3

import os
import sys
from logging import info as log

import results
import virt
import oscap
import versions


virt.setup_host()

prof = os.environ['PROFILE']
prof = f'xccdf_org.ssgproject.content_profile_{prof}'

if prof.endswith('_gui'):
    g = virt.Guest('gui_with_oscap')
else:
    g = virt.Guest('minimal_with_oscap')

if not g.can_be_snapshotted():
    ks = virt.Kickstart()
    if prof.endswith('_gui'):
        if versions.rhel < 8:
            ks.add_packages(['@^Server with GUI'])
        else:
            ks.add_packages(['@Server with GUI'])
    g.install(kickstart=ks)
    g.prepare_for_snapshot()

with g.snapshotted():
    #
    # remediate, reboot
    #

    g.ssh(f'oscap xccdf eval --profile {prof} --progress --remediate {oscap.datastream} ; chage -d 99999 root')
    g.soft_reboot()

    #
    # scan the remediated system
    #

    # old oscap mixes errors into --progress rule names without a newline,
    verbose = '--verbose INFO' if versions.oscap >= 1.3 else ''
    redir = '2>&1' if versions.oscap >= 1.3 else ''

    proc, lines = g.ssh_stream(f'oscap xccdf eval {verbose} --profile {prof} --progress --report report.html {oscap.datastream} {redir}')
    failed = oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')

if failed:
    results.report('info', 'html-report', logs=['report.html'])
    sys.exit(2)
else:
    results.report('pass', logs=['report.html'])

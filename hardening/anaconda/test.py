#!/usr/bin/python3

import os
from logging import info as log

import tmt
import virt
import oscap
import versions


virt.setup_host()

prof = os.environ['PROFILE']
prof = f'xccdf_org.ssgproject.content_profile_{prof}'

g = virt.Guest()

ks = virt.Kickstart()

oscap_conf = {
    #'content-type': 'rpm',
    'content-type': 'scap-security-guide',
    'profile': prof,
}
ks.add_oscap(oscap_conf)

ks.add_post('chage -d 99999 root')

if prof.endswith('_gui'):
    if versions.rhel < 8:
        ks.add_packages(['@^Server with GUI'])  
    else:
        ks.add_packages(['@Server with GUI'])

g.install(kickstart=ks)

with g.booted():
    # old oscap mixes errors into --progress rule names without a newline,
    verbose = '--verbose INFO' if versions.oscap >= 1.3 else ''
    redir = '2>&1' if versions.oscap >= 1.3 else ''

    proc, lines = g.ssh_stream(f'oscap xccdf eval {verbose} --profile {prof} --progress --report report.html {oscap.datastream} {redir}')
    failed = oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')

if failed:
    tmt.report('info', '/html-report', logs=['report.html'])
    sys.exit(2)
else:
    tmt.report('pass', logs=['report.html'])

#!/usr/bin/python3

import os
import sys

import results
import virt
import oscap
import versions


virt.setup_host()

profile = os.environ['PROFILE']
profile = f'xccdf_org.ssgproject.content_profile_{profile}'

g = virt.Guest()

ks = virt.Kickstart()

# remediate using Anaconda's oscap addon
oscap_conf = {
    'content-type': 'scap-security-guide',
    'profile': profile,
}
ks.add_oscap(oscap_conf)

ks.add_post('chage -d 99999 root')

if profile.endswith('_gui'):
    ks.add_package_group('Server with GUI')

g.install(kickstart=ks)

with g.booted():
    # old RHEL-7 oscap mixes errors into --progress rule names without a newline
    verbose = '--verbose INFO' if versions.oscap >= 1.3 else ''
    redir = '2>&1' if versions.oscap >= 1.3 else ''

    # scan the remediated system
    proc, lines = g.ssh_stream(f'oscap xccdf eval {verbose} --profile {profile} --progress '
                               f'--report report.html {oscap.datastream} {redir}')
    failed = oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')

if failed:
    results.report('info', logs=['report.html'])
    sys.exit(2)
else:
    results.report('pass', logs=['report.html'])

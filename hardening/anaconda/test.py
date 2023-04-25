#!/usr/bin/python3

import os
import sys

import util
import results
import virt
import oscap
import versions


virt.setup_host()

g = virt.Guest()

profile = os.environ['PROFILE']

# use kickstart from content, not ours
ks = virt.translate_ssg_kickstart(profile)

profile = f'xccdf_org.ssgproject.content_profile_{profile}'

ks.add_post('chage -d 99999 root')

if profile.endswith('_gui'):
    ks.add_package_group('Server with GUI')

oscap_conf = {
    'content-type': 'datastream',
    'content-url': f'http://{virt.NETWORK_HOST}:8088/contest-ds.xml',
    'profile': profile,
}
ks.add_oscap(oscap_conf)

# host a HTTP server with a datastream and let the guest download it
virt.firewalld_allow_port(8088)
srv = util.BackgroundHTTPServer(virt.NETWORK_HOST, 8088)
srv.add_file(util.get_datastream(), 'contest-ds.xml')
with srv:
    g.install(kickstart=ks)

with g.booted():
    # old RHEL-7 oscap mixes errors into --progress rule names without a newline
    verbose = '--verbose INFO' if versions.oscap >= 1.3 else ''
    redir = '2>&1' if versions.oscap >= 1.3 else ''

    # scan the remediated system
    proc, lines = g.ssh_stream(f'oscap xccdf eval {verbose} --profile {profile} --progress '
                               f'--report report.html /root/openscap_data/contest-ds.xml {redir}')
    failed = oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')

if failed:
    results.report('info', logs=['report.html'])
    sys.exit(2)
else:
    results.report('pass', logs=['report.html'])

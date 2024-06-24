#!/usr/bin/python3

import os

from lib import util, results, virt, oscap
from conf import remediation


virt.Host.setup()

g = virt.Guest()

profile = os.environ['PROFILE']

# use kickstart from content, not ours
ks = virt.translate_ssg_kickstart(profile)

profile = f'xccdf_org.ssgproject.content_profile_{profile}'

if os.environ.get('USE_SERVER_WITH_GUI'):
    ks.add_package_group('Server with GUI')

oscap_conf = {
    'content-type': 'datastream',
    'content-url': f'http://{virt.NETWORK_HOST}:8088/remediation-ds.xml',
    'profile': profile,
}
ks.add_oscap(oscap_conf)

oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())

# host a HTTP server with a datastream and let the guest download it
srv = util.BackgroundHTTPServer(virt.NETWORK_HOST, 8088)
srv.add_file('remediation-ds.xml')
with srv:
    g.install(kickstart=ks)

with g.booted():
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

util.subprocess_run(['gzip', '-9', 'results-arf.xml'], check=True)

results.report_and_exit(logs=['report.html', 'results-arf.xml.gz'])

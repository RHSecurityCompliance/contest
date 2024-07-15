#!/usr/bin/python3
import os
import subprocess

import shared
from lib import util, results, virt, oscap, versions
from conf import remediation


virt.Host.setup()

g = virt.Guest()

ks = virt.translate_ssg_kickstart(shared.profile)

# host a HTTP server with a datastream and let the guest download it
with util.BackgroundHTTPServer(virt.NETWORK_HOST, 0) as srv:
    oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())
    srv.add_file('remediation-ds.xml')

    host, port = srv.start()

    oscap_conf = {
        'content-type': 'datastream',
        'content-url': f'http://{host}:{port}/remediation-ds.xml',
        'profile': shared.profile_full,
    }
    ks.add_oscap(oscap_conf)

    g.install(kickstart=ks)

with g.booted(), util.get_content(build=False) as content_dir:
    g.copy_to(util.get_datastream(), 'ssg-ds.xml')
    shared.content_scan(g, 'ssg-ds.xml', html='ssg-report.html', arf='ssg-arf.xml')
    g.copy_from('ssg-report.html')
    g.copy_from('ssg-arf.xml')

    # There is always one (the latest) DISA benchmark in content src
    references = content_dir / 'shared' / 'references'
    disa_ds = next(
        references.glob(f'disa-stig-rhel{versions.rhel.major}-*-xccdf-scap.xml')
    )
    g.copy_to(disa_ds, 'disa-ds.xml')
    shared.disa_scan(g, 'disa-ds.xml', html='disa-report.html', arf='disa-arf.xml')
    g.copy_from('disa-report.html')
    g.copy_from('disa-arf.xml')

    # Compare ARFs via CaC/content script and report results from output
    compare_script = content_dir / 'utils' / 'compare_results.py'
    env = os.environ.copy()
    env['PYTHONPATH'] = str(content_dir)
    cmd = [compare_script, 'ssg-arf.xml', 'disa-arf.xml']
    proc = util.subprocess_run(cmd, env=env, universal_newlines=True, stdout=subprocess.PIPE)
    shared.comparison_report(proc.stdout.rstrip('\n'))

results.report_and_exit(logs=['ssg-report.html', 'disa-report.html'])

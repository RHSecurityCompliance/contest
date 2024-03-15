#!/usr/bin/python3

import os

from lib import results, versions, oscap, osbuild, util


osbuild.Host.setup()

g = osbuild.Guest()

profile = os.environ['PROFILE']

blueprint = osbuild.Blueprint(profile)
if os.environ.get('USE_SERVER_WITH_GUI'):
    blueprint.add_package_group('Server with GUI')

g.create(blueprint=blueprint, profile=profile)

profile = f'xccdf_org.ssgproject.content_profile_{profile}'

with g.booted():
    # RHEL-7 HTML report doesn't contain OVAL findings by default
    oval_results = '' if versions.oscap >= 1.3 else '--results results.xml --oval-results'

    # scan the remediated system
    proc, lines = g.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' {oval_results} --results-arf results-arf.xml {g.DATASTREAM}'
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')
    g.copy_from('results-arf.xml')

util.subprocess_run(['gzip', '-9', 'results-arf.xml'], check=True)

results.report_and_exit(logs=['report.html', 'results-arf.xml.gz', g.osbuild_log])

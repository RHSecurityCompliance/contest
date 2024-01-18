#!/usr/bin/python3

import os

from lib import results, versions, oscap, osbuild


osbuild.Host.setup()

g = osbuild.Guest()

profile = os.environ['PROFILE']

g.create(profile=profile)

profile = f'xccdf_org.ssgproject.content_profile_{profile}'

with g.booted():
    # old RHEL-7 oscap mixes errors into --progress rule names without a newline
    verbose = '--verbose INFO' if versions.oscap >= 1.3 else ''
    redir = '2>&1' if versions.oscap >= 1.3 else ''
    # RHEL-7 HTML report doesn't contain OVAL findings by default
    oval_results = '' if versions.oscap >= 1.3 else '--results results.xml --oval-results'

    # scan the remediated system
    proc, lines = g.ssh_stream(f'oscap xccdf eval {verbose} --profile {profile} --progress '
                               f'--report report.html {oval_results} '
                               f'{g.DATASTREAM} {redir}')
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')

results.report_and_exit(logs=['report.html', g.osbuild_log])

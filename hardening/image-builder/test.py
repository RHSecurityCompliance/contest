#!/usr/bin/python3

from lib import results, oscap, osbuild, util


osbuild.Host.setup()

g = osbuild.Guest()

profile = util.get_test_name().rpartition('/')[2]

g.create(profile=profile)

with g.booted():
    # scan the remediated system
    proc, lines = g.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf results-arf.xml {g.DATASTREAM}'
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')
    g.copy_from('results-arf.xml')

util.subprocess_run(['gzip', '-9', 'results-arf.xml'], check=True)

results.report_and_exit(logs=['report.html', 'results-arf.xml.gz', g.osbuild_log])

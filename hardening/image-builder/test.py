#!/usr/bin/python3

from lib import results, oscap, osbuild, util


osbuild.Host.setup()

g = osbuild.Guest()

profile = util.get_test_name().rpartition('/')[2]

ds = util.get_datastream()

# provide our modified DS via RpmPack to the VM as /root/contest-ds.xml,
# tell the 'oscap xccdf eval --remediate' called by osbuild-composer to use it
rpmpack = util.RpmPack()
rpmpack.add_file(ds, '/root/contest-ds.xml')

cmd = [
    'oscap', 'xccdf', 'generate', '--profile', profile,
    'fix', '--fix-type', 'blueprint',
    ds,
]
_, lines = util.subprocess_stream(cmd, check=True)
blueprint = osbuild.translate_oscap_blueprint(lines, profile, '/root/contest-ds.xml')

g.create(blueprint=blueprint, rpmpack=rpmpack)

with g.booted():
    # scan the remediated system
    proc, lines = g.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf results-arf.xml /root/contest-ds.xml'
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')
    g.copy_from('results-arf.xml')

util.subprocess_run(['gzip', '-9', 'results-arf.xml'], check=True)

results.report_and_exit(logs=['report.html', 'results-arf.xml.gz', g.osbuild_log])

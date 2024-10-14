#!/usr/bin/python3

from lib import util, results, virt, oscap
from conf import remediation


virt.Host.setup()

g = virt.Guest()

_, variant, profile = util.get_test_name().rsplit('/', 2)

oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())

# provide our modified DS via RpmPack to the VM as /root/remediation-ds.xml,
# tell the 'oscap xccdf eval --remediate' in %post to use it
rpmpack = util.RpmPack()
rpmpack.add_file('remediation-ds.xml', '/root/remediation-ds.xml')

cmd = [
    'oscap', 'xccdf', 'generate', '--profile', profile,
    'fix', '--fix-type', 'kickstart',
    'remediation-ds.xml',
]
_, lines = util.subprocess_stream(cmd, check=True)
ks = virt.translate_oscap_kickstart(lines, '/root/remediation-ds.xml')

if variant == 'with-gui':
    ks.packages.append('@Server with GUI')

g.install(kickstart=ks, rpmpack=rpmpack)

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

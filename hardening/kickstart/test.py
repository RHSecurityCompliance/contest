#!/usr/bin/python3

from lib import util, results, virt, oscap, metadata
from conf import remediation


virt.Host.setup()

g = virt.Guest()

profile = util.get_test_name().rpartition('/')[2]
with_fips = 'fips' in metadata.tags()
with_gui = 'with-gui' in metadata.tags()
with_uefi = 'uefi' in metadata.tags()

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

if with_gui:
    ks.packages.append('@Server with GUI')

g.install(
    kickstart=ks, rpmpack=rpmpack,
    secure_boot=with_uefi,
    kernel_args=['fips=1'] if with_fips else None,
)

with g.booted():
    # copy the original DS to the guest
    g.copy_to(util.get_datastream(), 'scan-ds.xml')
    # scan the remediated system
    proc, lines = g.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf scan-arf.xml scan-ds.xml',
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError(f"post-reboot oscap failed unexpectedly with {proc.returncode}")

    g.copy_from('report.html')
    g.copy_from('scan-arf.xml')

util.subprocess_run(['gzip', '-9', 'scan-arf.xml'], check=True)

results.report_and_exit(logs=['report.html', 'scan-arf.xml.gz'])

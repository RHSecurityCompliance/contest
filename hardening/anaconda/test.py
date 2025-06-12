#!/usr/bin/python3

from lib import util, results, virt, oscap, metadata
from conf import remediation


virt.Host.setup()

g = virt.Guest()

profile = util.get_test_name().rpartition('/')[2]
with_fips = 'fips' in metadata.tags()
with_gui = 'with-gui' in metadata.tags()

# use kickstart from content, not ours
ks_file = util.get_kickstart(profile)
ks = virt.translate_ssg_kickstart(ks_file)

if with_gui:
    ks.packages.append('@Server with GUI')

# host a HTTP server with a datastream and let the guest download it
with util.BackgroundHTTPServer(virt.NETWORK_HOST, 0) as srv:
    oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())
    srv.add_file('remediation-ds.xml')

    host, port = srv.start()

    oscap_conf = {
        'content-type': 'datastream',
        'content-url': f'http://{host}:{port}/remediation-ds.xml',
        'profile': profile,
    }
    ks.add_oscap_addon(oscap_conf)

    g.install(
        kickstart=ks,
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

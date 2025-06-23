#!/usr/bin/python3

import time
import subprocess
import tempfile

from lib import util, results, virt, metadata


profile = 'cis_workstation_l1'

# cis_workstation_l1 takes about 4-5 seconds to scan
oscap_timeout = 30

extra_packages = [
    'gdb',
    #'@Server with GUI',  # uncomment to test with GUI
]
extra_debuginfos = [
    'glibc',
    'openscap-scanner',
    'xmlsec1',
    'xmlsec1-openssl',
    'libtool-ltdl',
    'openssl-libs',
]

start_time = time.monotonic()

virt.Host.setup()
g = virt.Guest()
ks = virt.Kickstart()
ks.packages += extra_packages
g.install(kickstart=ks)

with g.booted():
    # copy our datastream to the guest
    g.copy_to(util.get_datastream(), 'scan-ds.xml')
    # install debugsource / debuginfo
    g.ssh(' '.join(['dnf', '-y', 'debuginfo-install', *extra_debuginfos]), check=True)
    # prepare gdb script
    with tempfile.NamedTemporaryFile(mode='w+t') as f:
        f.write(util.dedent('''
            generate-core-file oscap.core
            set logging file oscap-bt.txt
            set logging overwrite on
            set logging redirect on
            set logging enabled on
            thread apply all bt
            set logging enabled off
        '''))
        f.flush()
        g.copy_to(f.name, 'gdb.script')

    # run for all of the configured test duration, minus 600 seconds for safety
    # (running gdb, compressing corefile which takes forever, etc.)
    attempt = 1
    duration = metadata.duration_seconds() - oscap_timeout - 600
    util.log(f"trying to freeze oscap for {duration} total seconds")

    oscap_cmd = f'oscap xccdf eval --profile {profile} --progress scan-ds.xml'

    while time.monotonic() - start_time < duration:
        oscap_proc = g.ssh(oscap_cmd, func=util.subprocess_Popen)

        try:
            returncode = oscap_proc.wait(oscap_timeout)
            if returncode not in [0,2]:
                results.report(
                    'fail', f'attempt:{attempt}', f"oscap failed with {returncode}",
                )
                continue

        except subprocess.TimeoutExpired:
            # figure out oscap PID on the remote system
            pgrep = g.ssh('pgrep -n oscap', stdout=subprocess.PIPE, text=True)
            if pgrep.returncode != 0:
                results.report(
                    'warn',
                    f'attempt:{attempt}',
                    f"pgrep returned {pgrep.returncode}, oscap probably just finished "
                    "and we hit a rare race, moving on",
                )
                continue

            oscap_pid = pgrep.stdout.strip()

            # attach gdb to that PID
            g.ssh(f'gdb -n -batch -x gdb.script -p {oscap_pid}', check=True)

            # and download its results
            g.copy_from('oscap.core')
            g.copy_from('oscap-bt.txt')
            util.subprocess_run(['xz', '-e', '-9', 'oscap.core'], check=True)
            results.report(
                'fail', f'attempt:{attempt}', "oscap froze, gdb output available",
                logs=['oscap.core.xz', 'oscap-bt.txt'],
            )
            break

        finally:
            oscap_proc.terminate()
            oscap_proc.wait()

        results.report('pass', f'attempt:{attempt}')
        attempt += 1

results.report_and_exit()

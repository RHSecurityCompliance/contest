#!/usr/bin/python3

import os
import time
import subprocess
import tempfile

from lib import util, results, virt, oscap
from conf import remediation, partitions


profile = os.environ.get('PROFILE')
if not profile:
    raise RuntimeError("specify PROFILE via env variable, consider also TIMEOUT")

oscap_timeout = int(os.environ.get('TIMEOUT', 600))

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
]

start_time = time.monotonic()

virt.Host.setup()
g = virt.Guest()
ks = virt.Kickstart(partitions=partitions.partitions)
ks.packages += extra_packages
g.install(kickstart=ks)

with g.booted(safe_shutdown=True):
    # copy our datastreams to the guest
    ds = util.get_datastream()
    g.copy_to(ds, 'scan-ds.xml')
    oscap.unselect_rules(ds, 'remediation-ds.xml', remediation.excludes())
    g.copy_to('remediation-ds.xml')
    # install debugsource / debuginfo
    g.ssh(' '.join(['dnf', '-y', 'debuginfo-install', *extra_debuginfos]), check=True)
    # prepare gdb script
    with tempfile.NamedTemporaryFile(mode='w+t') as f:
        f.write(util.dedent('''
            generate-core-file /usr/oscap.core
            set logging file oscap-bt.txt
            set logging overwrite on
            set logging redirect on
            set logging enabled on
            thread apply all bt
            set logging enabled off
        '''))
        f.flush()
        g.copy_to(f.name, '/root/gdb.script')

g.prepare_for_snapshot()


def run_oscap(attempt, cmd):
    oscap = g.ssh(' '.join(cmd), func=util.subprocess_Popen)

    try:
        returncode = oscap.wait(oscap_timeout)
        if returncode not in [0,2]:
            raise RuntimeError(f"oscap failed with {returncode}")

    except subprocess.TimeoutExpired:
        # figure out oscap PID on the remote system
        pgrep = g.ssh('pgrep -n oscap', stdout=subprocess.PIPE, universal_newlines=True)
        if pgrep.returncode != 0:
            results.report(
                'warn',
                f'attempt:{attempt}',
                f"pgrep returned {pgrep.returncode}, oscap probably just finished "
                "and we hit a rare race, moving on",
            )
            return True

        oscap_pid = pgrep.stdout.strip()

        # attach gdb to that PID
        g.ssh(f'gdb -n -batch -x /root/gdb.script -p {oscap_pid}', check=True)

        # and download its results
        g.copy_from('/usr/oscap.core')
        g.copy_from('/root/oscap-bt.txt')
        util.subprocess_run(['xz', '-e', '-9', 'oscap.core'], check=True)
        results.report(
            'fail',
            f'attempt:{attempt}',
            "oscap froze, gdb output available",
            logs=['oscap.core.xz', 'oscap-bt.txt'],
        )

        return False

    finally:
        oscap.terminate()
        oscap.wait()

    results.report('pass', f'attempt:{attempt}')
    return True


testname = util.get_test_name().rpartition('/')[2]
cmd = ['oscap', 'xccdf', 'eval', '--profile', profile, '--progress']
if testname == 'remediate':
    cmd += ['--remediate', 'remediation-ds.xml']
else:
    cmd += ['scan-ds.xml']

# run for all of the configured test duration, minus 600 seconds for safety
# (running gdb, compressing corefile which takes forever, etc.)
attempt = 1
metadata = util.TestMetadata()
duration = metadata.duration_seconds() - oscap_timeout - 600
util.log(f"trying to freeze oscap for {duration} total seconds")
while time.monotonic() - start_time < duration:
    with g.snapshotted():
        if not run_oscap(attempt, cmd):
            break
    attempt += 1

results.report_and_exit()

#!/usr/bin/python3

import time
import signal
import subprocess

from lib import util, results, oscap, metadata


start_time = time.monotonic()

profile = 'anssi_bp28_high'

# sysctl rules only take about 1-2 seconds
oscap_timeout = 10

# unselect all rules in the specified profile, except for
# sysctl_* rules
ds = oscap.global_ds()
rules = ds.profiles[profile].rules
rules = {rule for rule in rules if not rule.startswith('sysctl_')}
oscap.unselect_rules(util.get_datastream(), 'scan-ds.xml', rules)

extra_debuginfos = [
    'glibc',
    'openscap-scanner',
    'xmlsec1',
    'xmlsec1-openssl',
    'libtool-ltdl',
    'openssl-libs',
]

util.subprocess_run(
    ['dnf', '-y', 'debuginfo-install', *extra_debuginfos], check=True, stderr=subprocess.PIPE,
)

with open('gdb.script', 'w') as f:
    f.write(util.dedent('''
        generate-core-file oscap.core
        set logging file oscap-bt.txt
        set logging overwrite on
        set logging redirect on
        set logging enabled on
        thread apply all bt
        set logging enabled off
    '''))

oscap_cmd = [
    'oscap', 'xccdf', 'eval', '--profile', profile, '--progress', 'scan-ds.xml',
]

# run for all of the configured test duration, minus 600 seconds for safety
# (running gdb, compressing corefile which takes forever, etc.)
attempt = 1
duration = metadata.duration_seconds() - oscap_timeout - 600
util.log(f"trying to freeze oscap for {duration} total seconds")

while time.monotonic() - start_time < duration:
    oscap_proc = util.subprocess_Popen(oscap_cmd)

    try:
        returncode = oscap_proc.wait(oscap_timeout)
        if returncode not in [0,2]:
            results.report(
                'fail', f'attempt:{attempt}', f"oscap failed with {returncode}",
            )
            continue

    except subprocess.TimeoutExpired:
        # figure out oscap PID on the remote system
        pgrep = util.subprocess_run(
            ['pgrep', '-n', 'oscap'],
            stdout=subprocess.PIPE, text=True,
        )
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
        util.subprocess_run(
            ['gdb', '-n', '-batch', '-x', 'gdb.script', '-p', oscap_pid],
            check=True, stderr=subprocess.PIPE,
        )

        results.report(
            'fail', f'attempt:{attempt}', "oscap froze, gdb output available",
            logs=['oscap.core', 'oscap-bt.txt'],
        )
        break

    finally:
        oscap_proc.send_signal(signal.SIGKILL)
        oscap_proc.wait()

    results.report('pass', f'attempt:{attempt}')
    attempt += 1

results.report_and_exit()

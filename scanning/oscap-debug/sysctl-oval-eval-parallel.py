#!/usr/bin/python3

import time
import subprocess
import concurrent.futures

from lib import util, results, metadata


# sysctl ovals only take about 1 second
OSCAP_TIMEOUT = 5


def run(fn):
    handle = util.subprocess_Popen(['oscap', 'oval', 'eval', fn])
    try:
        rc = handle.wait(OSCAP_TIMEOUT)
        return handle.pid, rc
    except subprocess.TimeoutExpired:
        return handle.pid, -1


start_time = time.monotonic()

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

with util.get_source_content() as content_dir:
    util.build_content(content_dir)
    build_dir = content_dir / util.CONTENT_BUILD_DIR
    oval_files = list(build_dir.glob('*/checks/oval/sysctl*.xml'))

# run for all the configured test duration, minus 600 seconds for safety
# (running gdb, compressing corefile which takes forever, etc.)
attempt = 1
duration = metadata.duration_seconds() - 600
util.log(f"trying to freeze oscap for {duration} total seconds")

while time.monotonic() - start_time < duration:
    with concurrent.futures.ProcessPoolExecutor() as executor:
        for filename, res in zip(oval_files, executor.map(run, oval_files)):
            oscap_pid, returncode = res
            if returncode == -1:
                # attach gdb to that PID
                gdb = util.subprocess_run(
                    ['gdb', '-n', '-batch', '-x', 'gdb.script', '-p', oscap_pid],
                )

                if gdb.returncode != 0:
                    results.report(
                        'warn',
                        f'attempt:{attempt}',
                        f"gdb returned {gdb.returncode}",
                    )
                    # something went wrong with gdb, let's try again
                    continue
                else:
                    results.report(
                        'fail', f'attempt:{attempt}', "oscap froze, gdb output available",
                        logs=['oscap.core', 'oscap-bt.txt'],
                    )
                    # we got the trace and the dump and now bail
                    duration = 0
                    break

            if returncode != 0:
                results.report(
                    'fail', f'attempt:{attempt}', f"oscap failed with {returncode}",
                )
                continue

            results.report('pass', f'attempt:{attempt}')
            attempt += 1

results.report_and_exit()

#!/usr/bin/python3

import atexit
import json
import re
import subprocess

from lib import util, results, virt, oscap, metadata
from conf import remediation, partitions

ERROR_WORDS_PATTERN = re.compile(
    '|'.join([
        'obsolete',
        'deprecated',
        r'notice[^a-zA-Z]',
        'error',
        'warning',
        'critical',
        'denied',
        'unknown',
        'no such file',
        'not found',
        r'no [^ ]+ found',
        r'fail([^a-zA-Z]|$)',
        'failed',
        'failure',
        'fatal',
        'invalid',
        'unable',
        'does not',
        'doesn\'t',
        'could not',
        'couldn\'t',
        'problem',
        'unexpected',
        'traceback',
        'please',
        'insecure',
        'for more',
        'cannot',
        'can\'t',
        r'[^a-zA-Z]bug([^a-zA-Z]|$)',
    ]),
    re.IGNORECASE,
)

# some errors can be ignored, e.g. chronyd failing to connect to the pool
IGNORE_ERROR_WORDS_PATTERN = re.compile(
    '|'.join([
        r'chronyd.+could not connect',
    ]),
    re.IGNORECASE,
)


def extract_error_messages(journal_text):
    """Extract error-matching journal lines, normalized without timestamps."""
    errors = set()
    for line in journal_text.splitlines():
        if IGNORE_ERROR_WORDS_PATTERN.search(line):
            continue
        if ERROR_WORDS_PATTERN.search(line):
            # remove timestamp
            normalized = re.sub(r'^\S+\s+\d+\s+\S+\s+\S+\s+', '', line)
            # replace process PID in "processname[123]: ..." with <PID> placeholder
            normalized = re.sub(r'^(\S+)\[\d+\]:', r'\1[<PID>]:', normalized)
            errors.add(normalized)
    return errors


virt.Host.setup()

profile = util.get_test_name().rpartition('/')[2]

guest_tag = virt.calculate_guest_tag(metadata.tags())
g = virt.Guest(guest_tag)

if not g.is_installed():
    ks = virt.Kickstart(partitions=partitions.partitions)
    g.install(
        kickstart=ks,
        kernel_args=['fips=1'] if 'fips' in metadata.tags() else None,
    )

g.prepare_for_snapshot()
atexit.register(g.cleanup_snapshot)

with g.snapshotted():
    journal_before = g.ssh(
        'journalctl -b -p 0..4 --no-pager', stdout=subprocess.PIPE, text=True,
    ).stdout

    proc = g.ssh(
        'systemctl list-units --state=failed --output=json-pretty',
        stdout=subprocess.PIPE, text=True,
    )
    try:
        failed_services_before = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(f"failed to parse systemctl list-units json output: {proc.stdout}")
    failed_before_names = {unit['unit'] for unit in failed_services_before}

    # copy our datastream to the guest
    oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())
    g.copy_to('remediation-ds.xml')

    # - remediate twice due to some rules being 'notapplicable'
    #   on the first pass
    for _ in range(2):
        cmd = [
            'oscap', 'xccdf', 'eval', '--profile', profile,
            '--progress', '--remediate', 'remediation-ds.xml',
        ]
        proc = g.ssh(' '.join(cmd))
        if proc.returncode not in [0,2]:
            raise RuntimeError(f"remediation oscap failed with {proc.returncode}")
        g.soft_reboot()

    journal_after = g.ssh(
        'journalctl -b -p 0..4 --no-pager', stdout=subprocess.PIPE, text=True,
    ).stdout

    proc = g.ssh(
        'systemctl list-units --state=failed --output=json-pretty',
        stdout=subprocess.PIPE, text=True,
    )
    try:
        failed_services_after = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(f"failed to parse systemctl list-units json output: {proc.stdout}")
    failed_after_names = {unit['unit'] for unit in failed_services_after}

    new_failed = failed_after_names - failed_before_names
    for service in sorted(new_failed):
        status_proc = g.ssh(
            f'systemctl status {service}', stdout=subprocess.PIPE, text=True,
        )
        status_file = f'{service}-status.txt'
        with open(status_file, 'w') as f:
            f.write(status_proc.stdout)
        results.report(
            'fail', service,
            'service failing after hardening',
            logs=[status_file],
        )

errors_before = extract_error_messages(journal_before)
errors_after = extract_error_messages(journal_after)

new_errors = errors_after - errors_before
if new_errors:
    for error in sorted(new_errors):
        results.report('fail', error)

with open('journal-errors-before.log', 'w') as f:
    f.write(journal_before)
with open('journal-errors-after.log', 'w') as f:
    f.write(journal_after)

results.report_and_exit(logs=[
    'journal-errors-before.log',
    'journal-errors-after.log',
])

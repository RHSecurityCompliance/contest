#!/usr/bin/python3

import atexit
import datetime
import json
import subprocess

from pathlib import Path

from lib import util, results, virt, oscap, metadata
from conf import remediation, partitions

PRIORITY_NAMES = {
    '0': 'emerg',
    '1': 'alert',
    '2': 'crit',
    '3': 'err',
}


def _get_source(entry):
    return entry.get('SYSLOG_IDENTIFIER') or entry.get('_SYSTEMD_UNIT') or 'unknown'


def _get_message(entry):
    message = entry.get('MESSAGE', '')
    if isinstance(message, list):
        message = bytes(message).decode(errors='replace')
    return message


def _parse_journal_entries(lines):
    """Yield (source, message, timestamp, priority) from journalctl JSON lines."""
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"failed to load journalctl json entry: {line!r}: {e}") from e
        timestamp = entry.get('SYSLOG_TIMESTAMP', '').strip() or None
        if not timestamp:
            rt = entry.get('__REALTIME_TIMESTAMP')
            if rt:
                dt = datetime.datetime.fromtimestamp(int(rt) / 1e6)
                timestamp = dt.strftime('%b %d %H:%M:%S')
        priority = entry.get('PRIORITY', '')
        yield _get_source(entry), _get_message(entry), timestamp, priority


def collect_journal_errors(guest, log_file):
    """
    Collect error messages (log level 0..3, see syslog(3)) from journalctl
    JSON output, and save the human-readable log for debugging.
    """
    errors = {}  # use dict to preserve order of entries
    _, lines = guest.ssh_stream('journalctl -b -p 0..3 --no-pager --output=json', check=True)
    with open(log_file, 'w') as f:
        for source, message, timestamp, priority in _parse_journal_entries(lines):
            key = f'{source}: {message}'
            name = PRIORITY_NAMES.get(str(priority))
            level = f'priority={priority}({name})' if name else f'priority={priority}'
            errors[key] = level
            ts = timestamp or '[no timestamp]'
            f.write(f'{ts} {level} {source}: {message}\n')
    return errors


def get_failed_services(guest):
    proc = guest.ssh(
        'systemctl list-units --state=failed --output=json',
        stdout=subprocess.PIPE, text=True,
    )
    try:
        units = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"failed to load systemctl list-units json output: {proc.stdout!r}: {e}",
        ) from e
    return {unit['unit'] for unit in units}


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
    errors_before = collect_journal_errors(g, 'journal-errors-before.log')
    failed_before_names = get_failed_services(g)

    # copy our datastream to the guest
    oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())
    g.copy_to('remediation-ds.xml')

    # remediate twice due to some rules being 'notapplicable'
    # on the first pass
    for _ in range(2):
        cmd = [
            'oscap', 'xccdf', 'eval', '--profile', profile,
            '--progress', '--remediate', 'remediation-ds.xml',
        ]
        proc = g.ssh(*cmd)
        if proc.returncode not in [0, 2]:
            raise RuntimeError(f"remediation oscap failed with {proc.returncode}")
        g.soft_reboot()

    # wait for all services to start (max 5 minutes)
    g.ssh('systemctl is-system-running --wait', timeout=300)

    errors_after = collect_journal_errors(g, 'journal-errors-after.log')
    failed_after_names = get_failed_services(g)

    new_failed = failed_after_names - failed_before_names
    for service in sorted(new_failed):
        proc = g.ssh(
            f'systemctl status {service}', stdout=subprocess.PIPE, text=True,
        )
        status_file = f'{service}-status.txt'
        Path(status_file).write_text(proc.stdout)
        results.report('fail', service, 'service failing after hardening', logs=[status_file])

    new_errors = {k: errors_after[k] for k in errors_after if k not in errors_before}
    for error, level in new_errors.items():
        results.report('fail', error, note=level)

results.report_and_exit(logs=[
    'journal-errors-before.log',
    'journal-errors-after.log',
])

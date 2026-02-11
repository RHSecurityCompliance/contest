"""
Functions and helpers for result management when working with
 - TMT (https://github.com/teemtee/tmt)
 - ATEX (https://github.com/RHSecurityCompliance/atex)

TMT uses the standard reporting behavior (result:respect), where
the overall test outcome is determined by the exit code. Sub-results
are reported as flat entries in tmt-report-results.yaml (the same file
that the tmt-report-result script writes to), and TMT converts them into
subresults under the main test result.
Log files for the main result are submitted via the tmt-file-submit
command, which copies them to the TMT data directory and registers them
to be included in the main result's log list.
See:
https://tmt.readthedocs.io/en/stable/spec/results.html
https://tmt.readthedocs.io/en/stable/spec/tests.html#spec-tests-result
"""

import os
import sys
import shutil
import subprocess
import collections
import json
import yaml
from pathlib import Path

from lib import util, waive

_valid_statuses = ['pass', 'fail', 'warn', 'error', 'info', 'skip']


# TODO: replace by collections.Counter on python 3.10+
class Counter(collections.defaultdict):
    def __init__(self):
        super().__init__(lambda: 0)

    def total(self):
        return sum(self.values())


global_counts = Counter()


def have_atex_api():
    """Return True if we can report results via ATEX Minitmt natively."""
    return ('ATEX_TEST_CONTROL' in os.environ)


def have_tmt_api():
    """Return True if we can report results via TMT natively."""
    return bool(os.environ.get('TMT_TEST_DATA'))


def _allowed_by_verbosity(status):
    env = os.environ.get('CONTEST_VERBOSE')
    if env:
        level = int(env)
    else:
        level = 1

    if level == 0:
        if status not in ['fail', 'error']:
            return False
    elif level == 1:
        if status not in ['fail', 'error', 'warn']:
            return False
    return True


def _write_tmt_subresult(subresult):
    """
    Append a single subresult entry to tmt-report-results.yaml.
    TMT converts the entry into a subresult under the main test result.
    """
    test_data = Path(os.environ['TMT_TEST_DATA'])
    # file that TMT reads for subresult entries (same as tmt-report-result writes to)
    results_path = test_data / 'tmt-report-results.yaml'
    with open(results_path, 'a') as f:
        yaml.dump([subresult], f)


def _tmt_file_submit(filepath):
    """
    Submit a file as a log for the main test result using tmt-file-submit.

    The script copies the file to TMT_TEST_DATA and registers it in
    TMT_TEST_SUBMITTED_FILES. TMT's internal executor then extends
    the main result's log list with the registered entries.
    """
    subprocess.run(
        ['tmt-file-submit', '-l', str(filepath)],
        stdout=subprocess.DEVNULL,
    )


def report_atex(status, name=None, note=None, logs=None, *, partial=False):
    if not partial:
        report_plain(status, name, note, logs)

    result = {
        'status': status,
    }
    # for subresults
    if name:
        result['name'] = name
    # not standard ATEX, Contest-specific
    if note:
        result['note'] = note
    # output of the test itself
    if not name:
        result['testout'] = 'output.txt'
    # partial result (non-partial to follow)
    if partial:
        result['partial'] = True

    # for protocol specification, see
    # https://github.com/RHSecurityCompliance/atex/blob/main/atex/minitmt/TEST_CONTROL.md
    # https://github.com/RHSecurityCompliance/atex/blob/main/atex/minitmt/RESULTS.md
    fd = int(os.environ['ATEX_TEST_CONTROL'])
    with os.fdopen(fd, 'wb', closefd=False) as control:
        if logs:
            files = []
            for log in logs:
                log = Path(log)
                files.append({
                    'name': log.name,
                    'length': log.stat().st_size,
                })
            result['files'] = files
        # send the JSON result, followed by any log data
        # (pause duration in case logs are being uploaded over slow link)
        json_data = json.dumps(result).encode()
        control.write(b'duration save\n')
        control.write(f'result {len(json_data)}\n'.encode())
        control.write(json_data)
        if logs:
            for log in logs:
                with open(log, 'rb') as f:
                    shutil.copyfileobj(f, control)
        control.write(b'duration restore\n')


def report_tmt(status, name=None, note=None, logs=None):
    test_data = Path(os.environ['TMT_TEST_DATA'])

    report_plain(status, name, note, logs)

    if name:
        # -- reporting a subresult --
        if not _allowed_by_verbosity(status):
            return

        subresult = {
            'name': f'/{name}',
            'result': status,
        }
        if note:
            subresult['note'] = [note]

        log_entries = []

        # put logs into a name-based subdir tree inside the data dir,
        # so that multiple results can have the same log names
        dst = test_data / name
        if logs:
            dst.mkdir(parents=True, exist_ok=True)
            for log in logs:
                log = Path(log)
                dstfile = dst / log.name
                # only copy if not already present (add_log() may have already copied it)
                if not dstfile.exists():
                    shutil.copyfile(log, dstfile)
                log_entries.append(str(dstfile.relative_to(test_data)))
        # add an empty log if none are present, to work around Testing Farm
        # and its Oculus result viewer expecting at least something
        elif os.environ.get('TESTING_FARM_REQUEST_ID'):
            dst.mkdir(parents=True, exist_ok=True)
            dummy = dst / 'dummy.txt'
            dummy.touch()
            log_entries.append(str(dummy.relative_to(test_data)))

        if log_entries:
            subresult['log'] = log_entries

        _write_tmt_subresult(subresult)
    else:
        # -- main test result --
        # TMT handles the main result via exit code; submit any directly-passed
        # logs via tmt-file-submit so TMT includes them in the main result
        # (logs added earlier via add_log() were already submitted)
        if logs:
            for log in logs:
                _tmt_file_submit(log)


def report_plain(status, name=None, note=None, logs=None):
    if not name:
        name = '/'
    note = f' ({note})' if note else ''
    logs = (' [' + ', '.join(str(x) for x in logs) + ']') if logs else ''
    util.log(f'{status.upper()} {name}{note}{logs}')


def report(status, name=None, note=None, logs=None):
    """
    Report a test result.

    'name' will be appended to the currently running test name,
    allowing the test to report one or more sub-results.
    If empty, result for the test itself is reported.

    'logs' is a list of file paths (relative to CWD) to be copied
    or uploaded, and associated with the new result.

    Returns the final 'status', potentially modified by the waiving logic.
    """
    if status not in _valid_statuses:
        raise ValueError(f"{status} is not a valid status")

    # apply to all report variants
    if name:
        name = util.make_printable(name)
    if note:
        note = util.make_printable(note)

    status, name, note = waive.rewrite_result(status, name, note)

    if have_atex_api():
        report_atex(status, name, note, logs)
    elif have_tmt_api():
        report_tmt(status, name, note, logs)
    else:
        report_plain(status, name, note, logs)

    global_counts[status] += 1

    return status


def add_log(*logs):
    """
    Add log file(s) to be associated with the main test result.

    The log file(s) will be processed immediately:
    - For ATEX: uploaded incrementally using report_atex() with partial=True
    - For TMT: submitted via tmt-file-submit so they appear on the main result

    This allows logs to be added incrementally throughout the test,
    and ensures they're available even if the test later fails with a traceback.

    Multiple logs can be added by calling this function multiple times,
    or by passing multiple arguments.
    """
    if have_atex_api():
        # partial results are overwritten by the final result so we report an error partial result
        # with logs in case test crashes or fails with an exception, see
        # https://github.com/RHSecurityCompliance/atex/blob/main/atex/executor/RESULTS.md#partial-results
        report_atex(status='error', logs=logs, partial=True)
    elif have_tmt_api():
        for log in logs:
            _tmt_file_submit(log)


def report_and_exit(status=None, note=None, logs=None):
    """
    Report a result for the test itself and exit with 0 or 2, depending
    on whether there were any failures reported during execution of
    the test.

    Additional logs can be passed via the 'logs' parameter.
    """
    # figure out overall test status based on previously reported results
    if not status:
        # only failures, no errors --> fail
        if global_counts['fail'] > 0 and global_counts['error'] == 0:
            status = 'fail'
        # any errors anywhere --> error
        elif global_counts['error'] > 0:
            status = 'error'
        # no errors, no fails --> pass
        else:
            status = 'pass'

    # report and pass the status through the waiving logic
    status = report(status=status, note=note, logs=logs)

    # exit based on the new status
    if status == 'fail':
        sys.exit(2)
    elif status in ['pass', 'info', 'warn', 'skip']:
        sys.exit(0)
    else:
        sys.exit(1)

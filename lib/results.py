"""
Functions and helpers for result management when working with
 - TMT (https://github.com/teemtee/tmt)
 - ATEX (https://github.com/RHSecurityCompliance/atex)

TMT has a 'result:custom' feature (in test's main.fmf), which allows us to
supply completely custom results as a YAML file, and TMT will use it as-is
to represent a result from the test itself, and any results "under" it,
effectively allowing a test to report more than 1 result.
"""

import os
import sys
import shutil
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
global_logs = []


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


# read test pass/fail/error/etc. counts from an existing results file
def _count_yaml_results(path):
    counter = Counter()
    with open(path) as f:
        previous = yaml.safe_load(f)
    for item in previous:
        if 'result' in item:
            counter[item['result']] += 1
    return counter


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


def report_tmt(status, name=None, note=None, logs=None, *, add_output=True):
    test_data = Path(os.environ['TMT_TEST_DATA'])
    results_path = Path(test_data / 'results.yaml')

    # try to find and re-read previous results.yaml, in case this test
    # has been rerun in-place by TMT, like ie. after a reboot
    if global_counts.total() == 0 and results_path.exists():
        previous = _count_yaml_results(results_path)
        global_counts.update(previous)

    report_plain(status, name, note, logs)

    if not _allowed_by_verbosity(status) and name:
        return

    if not name:
        name = '/'  # https://github.com/teemtee/tmt/issues/1855
    else:
        name = f'/{name}'

    new_result = {
        'name': name,
        'result': status,
    }
    if note:
        new_result['note'] = [note]

    log_entries = []

    if add_output and name == '/':
        log_entries.append('../output.txt')

    # put logs into a name-based subdir tree inside the data dir,
    # so that multiple results can have the same log names
    dst = test_data / name[1:]
    # copy logs to tmt test data dir
    if logs:
        dst.mkdir(parents=True, exist_ok=True)
        for log in logs:
            log = Path(log)
            dstfile = dst / log.name
            shutil.copyfile(log, dstfile)
            log_entries.append(str(dstfile.relative_to(test_data)))
    # add an empty log if none are present, to work around Testing Farm
    # and its Oculus result viewer expecting at least something
    elif os.environ.get('TESTING_FARM_REQUEST_ID'):
        dst.mkdir(parents=True, exist_ok=True)
        dummy = (dst / 'dummy.txt')
        dummy.touch()
        log_entries.append(str(dummy.relative_to(test_data)))

    if log_entries:
        new_result['log'] = log_entries

    with open(results_path, 'a') as f:
        yaml.dump([new_result], f)


def report_plain(status, name=None, note=None, logs=None):
    if not name:
        name = '/'
    note = f' ({note})' if note else ''
    logs = (' [' + ', '.join(str(x) for x in logs) + ']') if logs else ''
    util.log(f'{status.upper()} {name}{note}{logs}')


def report(status, name=None, note=None, logs=None, *, add_output=True):
    """
    Report a test result.

    'name' will be appended to the currently running test name,
    allowing the test to report one or more sub-results.
    If empty, result for the test itself is reported.

    'logs' is a list of file paths (relative to CWD) to be copied
    or uploaded, and associated with the new result.

    'add_output' specifies whether to add the test's own std* console
    output, as captured by TMT, to the list of logs whenever 'name'
    is empty.

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
        report_tmt(status, name, note, logs, add_output=add_output)
    else:
        report_plain(status, name, note, logs)

    global_counts[status] += 1

    return status


def add_log(*logs):
    """
    Add log file(s) to be associated with the main test result as reported
    by the report_and_exit() function.

    The log file(s) will be processed immediately:
    - For ATEX: uploaded incrementally using report_atex() with partial=True
    - For TMT: copied to the TMT data directory and stored in global_logs for later upload
    - For plain: stored in global_logs for later upload

    This allows logs to be added incrementally throughout the test,
    and ensures they're available even if the test later fails with a traceback.

    Multiple logs can be added by calling this function multiple times,
    or by passing multiple arguments.
    All accumulated logs will be included in the final report by report_and_exit()
    except for ATEX which handles this itself.
    """
    if have_atex_api():
        # partial results are overwritten by the final result so we report an error partial result
        # with logs in case test crashes or fails with an exception, see
        # https://github.com/RHSecurityCompliance/atex/blob/main/atex/executor/RESULTS.md#partial-results
        report_atex(status='error', logs=logs, partial=True)
    elif have_tmt_api():
        test_data = Path(os.environ['TMT_TEST_DATA'])
        for log in logs:
            log = Path(log)
            dstfile = test_data / log.name
            shutil.copyfile(log, dstfile)
            global_logs.append(str(dstfile.relative_to(test_data)))
    else:
        global_logs.extend(str(log) for log in logs)


def report_and_exit(status=None, note=None, logs=None):
    """
    Report a result for the test itself and exit with 0 or 2, depending
    on whether there were any failures reported during execution of
    the test.

    Any logs previously added via add_log() will be automatically included.
    Additional logs can still be passed via the 'logs' parameter.
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

    # combine accumulated logs with any directly passed logs
    all_logs = (global_logs + logs) if logs else global_logs

    # report and pass the status through the waiving logic, use combined logs or None if empty
    status = report(status=status, note=note, logs=(all_logs or None))

    # exit based on the new status
    if status == 'fail':
        sys.exit(2)
    elif status in ['pass', 'info', 'warn', 'skip']:
        sys.exit(0)
    else:
        sys.exit(1)

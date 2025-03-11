"""
Functions and helpers for result management when working with
 - TMT (https://github.com/teemtee/tmt)
 - Beaker (https://beaker-project.org/docs/server-api/index.html)

TMT has a 'result:custom' feature (in test's main.fmf), which allows us to
supply completely custom results as a YAML file, and TMT will use it as-is
to represent a result from the test itself, and any results "under" it,
effectively allowing a test to report more than 1 result.

Beaker uses the HTTP API, connecting to a local labcontroller.
"""

import os
import sys
import shutil
import collections
import requests
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


def have_tmt_api():
    """Return True if we can report results via TMT natively."""
    return bool(os.environ.get('TMT_TEST_DATA'))


def have_beaker_api():
    """Return True if we have access to Beaker results API."""
    required_vars = [
        'LAB_CONTROLLER', 'RECIPEID', 'TASKID',
    ]
    return all(os.environ.get(x) for x in required_vars)


def _allowed_by_verbosity(status):
    env = os.environ.get('CONTEST_VERBOSE')
    if env:
        level = int(env)
    else:
        # be non-verbose in Beaker by default
        level = 0 if have_beaker_api() else 1

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


def report_beaker(status, name=None, note=None, logs=None):
    report_plain(status, name, note, logs)

    if not _allowed_by_verbosity(status) and name:
        return

    labctl = os.environ['LAB_CONTROLLER']
    recipeid = os.environ['RECIPEID']
    taskid = os.environ['TASKID']

    if not name:
        name = '/'

    if status == 'pass':
        beaker_status = 'Pass'
    elif status == 'warn':
        # 'Warn' causes tcms-results to treat it as a failure,
        # in fact, anything non-'Pass' does
        beaker_status = 'Pass'
    elif status == 'info':
        beaker_status = 'None'
    else:
        beaker_status = 'Fail'

    url = f'http://{labctl}:8000/recipes/{recipeid}/tasks/{taskid}/results/'
    payload = {
        'path': f'{status}: {name}' + (f' ({note})' if note else ''),
        'result': beaker_status,
    }
    r = requests.post(url, data=payload)
    if r.status_code != 201:
        util.log(f"reporting to {url} failed with {r.status_code}")
        return

    if logs:
        for log in logs:
            logpath = r.headers['Location'] + '/logs/' + Path(log).name
            with open(log, 'rb') as f:
                put = requests.put(logpath, data=f)
                if put.status_code != 204:
                    util.log(f"uploading log {logpath} failed with {put.status_code}")


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
        raise SyntaxError(f"{status} is not a valid status")

    # apply to all report variants
    if name:
        name = util.make_printable(name)
    if note:
        note = util.make_printable(note)

    status, name, note = waive.rewrite_result(status, name, note)

    if have_beaker_api():
        report_beaker(status, name, note, logs)
    elif have_tmt_api():
        report_tmt(status, name, note, logs, add_output=add_output)
    else:
        report_plain(status, name, note, logs)

    global_counts[status] += 1

    return status


def report_and_exit(status=None, note=None, logs=None):
    """
    Report a result for the test itself and exit with 0 or 2, depending
    on whether there were any failures reported during execution of
    the test.
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

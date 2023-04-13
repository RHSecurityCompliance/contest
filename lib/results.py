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
import re
import logging
import shutil
import textwrap
import requests
from pathlib import Path

import util

_log = logging.getLogger(__name__).debug

_valid_statuses = ['pass', 'fail', 'warn', 'error', 'info']

RESULTS_FILE = 'results.yaml'


def _compose_results_yaml(keyvals):
    """
    Trivial hack to output simple YAML without a PyYAML depedency.
    """
    def printval(x):
        if type(x) is list:
            # python str(list) format is compatible with YAML
            return str(x)
        else:
            # account for name/note having complex content
            x = x.replace('"', '\\"')
            return f'"{x}"'
    it = iter(keyvals.items())
    # prefix first item with '-'
    key, value = next(it)
    out = f'- {key}: {printval(value)}\n'
    for key, value in it:
        out += f'  {key}: {printval(value)}\n'
    return out


def _sanitize_yaml_id(string):
    """
    Remove anything that shouldn't appear in a YAML identifier (ie. key name),
    whether the limitation comes from YAML itself, or its use by TMT.
    """
    return re.sub(r'[^\w/ _-]', '', string, flags=re.A).strip()


def report_tmt(status, name=None, note=None, logs=None):
    if not name:
        name = '/'  # https://github.com/teemtee/tmt/issues/1855
    else:
        name = f'/{name}'

    new_result = {
        'name': name,
        'result': status,
    }
    if note:
        new_result['note'] = note

    test_data = Path(os.environ['TMT_TEST_DATA'])

    # copy logs to tmt test data dir
    if logs:
        log_entries = []
        for log in logs:
            log = Path(log)
            # put logs into a name-based subdir tree inside the data dir,
            # so that multiple results can have the same log names
            dst = test_data / name[1:]
            dst.mkdir(parents=True, exist_ok=True)
            dstfile = dst / log.name
            _log(f"copying log {log} to {dstfile}")
            shutil.copyfile(log, dstfile)
            log_entries.append(str(dstfile.relative_to(test_data)))
        new_result['log'] = log_entries

    yaml_addition = _compose_results_yaml(new_result)
    _log(f"appending to results:\n{textwrap.indent(yaml_addition.rstrip(), '  ')}")

    with open(test_data / RESULTS_FILE, 'a') as f:
        f.write(yaml_addition)


def report_beaker(status, name=None, note=None, logs=None):
    labctl = os.environ['LAB_CONTROLLER']
    taskid = os.environ['TASKID']
    recipeid = os.environ['RECIPEID']
    taskid = os.environ['TASKID']

    if not name:
        name = '/'

    if status == 'pass':
        status = 'Pass'
    elif status == 'warn':
        status = 'Warn'
    elif status == 'info':
        status = 'None'
    else:
        status = 'Fail'

    url = f'http://{labctl}:8000/recipes/{recipeid}/tasks/{taskid}/results/'
    payload = {
        'path': f'{name} ({note})' if note else name,
        'result': status,
    }
    _log(f'result: {payload}')
    r = requests.post(url, data=payload)
    if r.status_code != 201:
        _log(f"reporting to {url} failed with {r.status_code}")
        return

    if logs:
        for log in logs:
            logpath = r.headers['Location'] + '/logs/' + Path(log).name
            with open(log, 'rb') as f:
                r = requests.put(logpath, data=f)
                if r.status_code != 204:
                    _log(f"uploading log {logpath} failed with {r.status_code}")


def report_plain(status, name=None, note=None, logs=None):
    _log(f'result: {name}:{status} ({note})')


def report(status, name=None, note=None, logs=None):
    """
    Report a test result.

    'name' will be appended to the currently running test name,
    allowing the test to report one or more sub-results.
    If empty, result for the test itself is reported.

    'logs' is a list of file paths (relative to CWD) to be copied
    or uploaded, and associated with the new result.
    """
    if status not in _valid_statuses:
        raise SyntaxError(f"{status} is not a valid status")

    # apply to all report variants
    if name:
        name = _sanitize_yaml_id(name)
    if note:
        note = util.make_printable(note)

    taskpath = os.environ.get('RSTRNT_TASKPATH')
    if taskpath and taskpath.endswith('/distribution/wrapper/fmf'):
        return report_beaker(status, name, note, logs)
    elif 'TMT_TEST_DATA' in os.environ:
        return report_tmt(status, name, note, logs)
    else:
        return report_plain(status, name, note, logs)

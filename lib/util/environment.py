import os
import re
import time
import shutil

from .subprocess import subprocess_run


def running_in_tmt():
    """Return True if running under TMT."""
    return bool(os.environ.get('TMT_TEST_DATA'))


def reboot():
    """Reboot the system using whatever means appropriate."""
    # flush buffers to disk, just in case reboot doesn't do it
    os.sync()
    if shutil.which('tmt-reboot'):
        subprocess_run('tmt-reboot')
    elif shutil.which('rstrnt-reboot'):
        subprocess_run('rstrnt-reboot')
    else:
        subprocess_run('reboot')
    while True:
        time.sleep(1000000)


def get_reboot_count():
    """Return the number of OS reboots the test underwent."""
    for var in ['TMT_REBOOT_COUNT', 'RSTRNT_REBOOTCOUNT']:
        count = os.environ.get(var)
        if count:
            return int(count)
    raise RuntimeError("could not determine reboot count")


def get_test_name():
    """
    Return a full (absolute) test name of the currently running test.
    Ie. '/hardening/oscap/stig'.
    """
    # natively running under TMT
    name = os.environ.get('TMT_TEST_NAME')
    if name:
        return name
    # under Restraint (Beaker, OSCI, etc.)
    name = os.environ.get('RSTRNT_TASKNAME', '')
    # - without leading '(gitrepo) '
    match = re.fullmatch('\([^\)]*\) (/.+)', name)
    if match:
        return match.group(1)
    # unknown
    raise RuntimeError("could not determine test name")

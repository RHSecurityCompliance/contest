import os
import time

from .subprocess import subprocess_run


def running_in_beaker():
    """Return True if running in Beaker under the FMF wrapper."""
    taskpath = os.environ.get('RSTRNT_TASKPATH')
    return bool(taskpath and taskpath.endswith('/distribution/wrapper/fmf'))


def running_in_tmt():
    """Return True if running under TMT."""
    return bool(os.environ.get('TMT_TEST_DATA'))


def reboot():
    """Reboot the system using whatever means appropriate."""
    # flush buffers to disk, just in case reboot doesn't do it
    os.sync()
    if running_in_tmt():
        subprocess_run('tmt-reboot')
    elif running_in_beaker():
        subprocess_run('rstrnt-reboot')
    else:
        subprocess_run('reboot')
    while True:
        time.sleep(1000000)


def get_reboot_count():
    """Return the number of OS reboots the test underwent."""
    if running_in_tmt():
        return int(os.environ.get('TMT_REBOOT_COUNT'))
    elif running_in_beaker():
        return int(os.environ.get('RSTRNT_REBOOTCOUNT'))
    else:
        raise RuntimeError("not TMT/Beaker, could not determine reboot count")


def get_test_name():
    """
    Return a full (absolute) test name of the currently running test.
    Ie. '/hardening/oscap/stig'.
    """
    if running_in_tmt():
        return os.environ.get('TMT_TEST_NAME')  # tmt natively
    elif running_in_beaker():
        return os.environ.get('TEST')
    else:
        raise RuntimeError("not TMT/Beaker, could not determine test name")

import os
import re
import inspect
import subprocess
from pathlib import Path

import versions


# directory with all these modules, and potentially more files
# - useful until TMT can parametrize 'environment:' with variable expressions,
#   so we could add the libdir to PATH and PYTHONPATH
libdir = Path(inspect.getfile(inspect.currentframe())).parent

# content locations
DATASTREAMS = Path(os.getenv('CONTEST_DATASTREAMS', '/usr/share/xml/scap/ssg/content'))
PLAYBOOKS = Path(os.getenv('CONTEST_PLAYBOOKS', '/usr/share/scap-security-guide/ansible'))
KICKSTARTS = Path(os.getenv('CONTEST_KICKSTARTS', '/usr/share/scap-security-guide/kickstart'))


def get_datastream():
    if versions.rhel:
        return DATASTREAMS / f'ssg-rhel{versions.rhel.major}-ds.xml'
    else:
        raise RuntimeError("cannot find datastream for non-RHEL")


def get_playbook(profile):
    if versions.rhel:
        return PLAYBOOKS / f'rhel{versions.rhel.major}-playbook-{profile}.yml'
    else:
        raise RuntimeError("cannot find playbook for non-RHEL")


def get_kickstart(profile):
    if versions.rhel:
        return KICKSTARTS / f'ssg-rhel{versions.rhel.major}-{profile}-ks.cfg'
    else:
        raise RuntimeError("cannot find kickstart for non-RHEL")


def make_printable(obj):
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode()
    elif not isinstance(obj, str):
        obj = str(obj)
    obj = re.sub(r'\n\r', ' ', obj)
    obj = re.sub(r'''[^\w\-\+~\.,:;!\?@#$%^&*=\(\)<>{}\[\]'"`/\\| ]''', '', obj, flags=re.A)
    return obj.strip()


def proc_stream(cmd, check=False, **kwargs):
    """
    Run 'cmd' via subprocess.Popen() and return an iterator over any lines
    the command outputs on stdout.

    With 'check' set to True, raise a CalledProcessError if the 'cmd' failed.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, **kwargs)

    def generate_lines():
        for line in proc.stdout:
            yield line.decode('ascii', errors='ignore').rstrip('\n')
        code = proc.wait()
        if code > 0 and check:
            raise subprocess.CalledProcessError(cmd=cmd, returncode=code)

    return (proc, generate_lines())


def running_in_beaker():
    """
    Return True if running in Beaker under the FMF wrapper.
    """
    taskpath = os.environ.get('RSTRNT_TASKPATH')
    return bool(taskpath and taskpath.endswith('/distribution/wrapper/fmf'))


def running_in_tmt():
    """
    Return True if running under TMT.
    """
    return bool(os.environ.get('TMT_TEST_DATA'))

import os
import re
import logging
import shutil
import inspect
import subprocess
import multiprocessing
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

from . import versions

_log = logging.getLogger(__name__).debug

# directory with all these modules, and potentially more files
# - useful until TMT can parametrize 'environment:' with variable expressions,
#   so we could add the libdir to PATH and PYTHONPATH
# TODO: after RHEL-7, replace with importlib.resources to access files
#       in the python package hierarchy, python 3.7+
libdir = Path(inspect.getfile(inspect.currentframe())).parent


def get_datastream():
    base_dir = Path('/usr/share/xml/scap/ssg/content')
    if versions.rhel:
        return base_dir / f'ssg-rhel{versions.rhel.major}-ds.xml'
    else:
        raise RuntimeError("cannot find datastream for non-RHEL")


def get_playbook(profile):
    base_dir = Path('/usr/share/scap-security-guide/ansible')
    if versions.rhel:
        return base_dir / f'rhel{versions.rhel.major}-playbook-{profile}.yml'
    else:
        raise RuntimeError("cannot find playbook for non-RHEL")


def get_kickstart(profile):
    base_dir = Path('/usr/share/scap-security-guide/kickstart')
    if versions.rhel:
        return base_dir / f'ssg-rhel{versions.rhel.major}-{profile}-ks.cfg'
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


class _BackgroundHTTPServerHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        mapping = self.server.file_mapping
        if self.path not in mapping:
            self.send_response(404)
            self.end_headers()
            return
        with open(mapping[self.path], 'rb') as f:
            self.send_response(200)
            self.end_headers()
            shutil.copyfileobj(f, self.wfile)

    def log_message(self, form, *args):
        self.server.log(form % args)


class BackgroundHTTPServer(HTTPServer):
    def __init__(self, host, port):
        self.log = logging.getLogger(f'{__name__}.{self.__class__.__name__}').debug
        self.file_mapping = {}
        self.listen_port = port
        self.firewalld_zones = []
        super().__init__((host, port), _BackgroundHTTPServerHandler)

    def add_file(self, fspath, urlpath=None):
        if not urlpath:
            urlpath = Path(fspath).name
        self.file_mapping[f'/{urlpath}'] = fspath

    def __enter__(self):
        self.log(f"starting with: {self.file_mapping}")
        # allow the target port on the firewall
        if shutil.which('firewall-cmd'):
            res = subprocess_run(
                ['firewall-cmd', '--state'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                res = subprocess_run(
                    ['firewall-cmd', '--get-zones'], stdout=subprocess.PIPE,
                    universal_newlines=True, check=True)
                self.firewalld_zones = res.stdout.strip().split(' ')
                for zone in self.firewalld_zones:
                    subprocess_run(
                        ['firewall-cmd', f'--zone={zone}', f'--add-port={self.listen_port}/tcp'],
                        stdout=subprocess.DEVNULL, check=True)
        proc = multiprocessing.Process(target=self.serve_forever)
        self.process = proc
        proc.start()

    def __exit__(self, exc_type, exc_value, traceback):
        self.log("ending")
        self.process.terminate()
        self.process.join()
        # remove allow rules from the firewall
        for zone in self.firewalld_zones:
            subprocess_run(
                ['firewall-cmd', f'--zone={zone}', f'--remove-port={self.listen_port}/tcp'],
                stdout=subprocess.DEVNULL, check=True)


def subprocess_run(*popenargs, **kwargs):
    """
    A simple wrapper for the real subprocess.run() that logs the command used.
    """
    _log(popenargs)
    return subprocess.run(*popenargs, **kwargs)

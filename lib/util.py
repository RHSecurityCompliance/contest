import os
import sys
import re
import shutil
import inspect
import subprocess
import multiprocessing
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

from . import versions

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
        self.file_mapping = {}
        self.listen_port = port
        self.firewalld_zones = []
        super().__init__((host, port), _BackgroundHTTPServerHandler)

    def add_file(self, fspath, urlpath=None):
        if not urlpath:
            urlpath = Path(fspath).name
        self.file_mapping[f'/{urlpath}'] = fspath

    def __enter__(self):
        log(f"starting with: {self.file_mapping}")
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
        log("ending")
        self.process.terminate()
        self.process.join()
        # remove allow rules from the firewall
        for zone in self.firewalld_zones:
            subprocess_run(
                ['firewall-cmd', f'--zone={zone}', f'--remove-port={self.listen_port}/tcp'],
                stdout=subprocess.DEVNULL, check=True)


def _format_subprocess_cmd(cmd):
    if isinstance(cmd, (list, tuple)):
        return ' '.join(str(x) for x in cmd)
    else:
        return cmd


def subprocess_run(cmd, **kwargs):
    """
    A simple wrapper for the real subprocess.run() that logs the command used.
    """
    # when logging, skip current stack frame - report the place we were called
    # from, not util.subprocess_run itself
    log(f'running: {_format_subprocess_cmd(cmd)}', skip_caller=True)
    return subprocess.run(cmd, **kwargs)


def subprocess_stream(cmd, check=False, **kwargs):
    """
    Run 'cmd' via subprocess.Popen() and return an iterator over any lines
    the command outputs on stdout.

    With 'check' set to True, raise a CalledProcessError if the 'cmd' failed.
    """
    log(f'running: {_format_subprocess_cmd(cmd)}', skip_caller=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, **kwargs)

    def generate_lines():
        for line in proc.stdout:
            yield line.decode('ascii', errors='ignore').rstrip('\n')
        code = proc.wait()
        if code > 0 and check:
            raise subprocess.CalledProcessError(cmd=cmd, returncode=code)

    return (proc, generate_lines())


def log(msg, *, skip_caller=False):
    """
    An intelligent replacement for the basic functionality of the python
    'logging' module. Simply call this function from anywhere and it should
    print out the proper context of the caller function.

    When called from a module directly, it just prints the message:
        2023-05-18 01:29:16 test.py:14: some message

    When called from a function (class or not) of the running module,
    it adds the function name and a line number inside that function.
    The filename/lineno is the place of the myfunc() function call:
        2023-05-18 01:29:16 test.py:25: myfunc:13: some message

    In a more complex/nested call stack, the leftmost filename/lineno
    remains the base module executed (as an entrypoint), with the
    right side function/module name being the topmost stack frame.
    If myfunc is in another module, it could look like:
        2023-05-18 01:29:16 test.py:27: some.module.myfunc:9: some message

    Note that this operates on file/function names, and while there is a crude
    guess for a classname of a method, that method might still appear as
    module.function instead of module.Class.function, due to Python stackframe
    limitations.

    With 'skip_caller', report module or function that called the function
    which called log(), rather than the function which called log(). This is
    useful for lightweight wrappers, as the call of the wrapper gets logged,
    rather than log() inside the wrapper.
    """
    stack = inspect.stack()
    if skip_caller:
        if stack[1].function == '<module>':
            raise SyntaxError("can't use skip_caller when called directly from module code")
        stack = stack[2:]
    else:
        stack = stack[1:]

    # bottom of the stack, or runpy executed module
    for frame_info in stack:
        if frame_info.function == '<module>':
            break
    module = frame_info

    log_prefix = datetime.now().strftime('%Y-%m-%d %H:%M:%S ')
    log_prefix += f'{Path(module.filename).name}:{module.lineno}'

    # last (topmost) function that isn't us
    parent = stack[0]
    function = parent.function

    # if the function has 'self' and it looks like a class instance,
    # prepend it to the function name
    p_locals = parent.frame.f_locals
    if 'self' in p_locals:
        self = p_locals['self']
        if hasattr(self, '__class__') and inspect.isclass(self.__class__):
            function = f'{self.__class__.__name__}.{function}'

    # don't report module name of a function if it's the same as running module
    if parent.filename != module.filename:
        parent_modname = parent.frame.f_globals['__name__']
        log_prefix += f': {parent_modname}.{function}:{parent.lineno}'
    elif parent.function != '<module>':
        log_prefix += f': {function}:{parent.lineno}'

    sys.stdout.write(f'{log_prefix}: {msg}\n')
    sys.stdout.flush()

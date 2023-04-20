import re
import inspect
import subprocess
from pathlib import Path

# directory with all these modules, and potentially more files
# - useful until TMT can parametrize 'environment:' with variable expressions,
#   so we could add the libdir to PATH and PYTHONPATH
libdir = Path(inspect.getfile(inspect.currentframe())).parent


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

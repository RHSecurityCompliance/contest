import subprocess

from .log import log


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

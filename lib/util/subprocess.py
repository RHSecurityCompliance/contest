import subprocess

from lib import util


def _format_subprocess_cmd(cmd):
    if isinstance(cmd, (list, tuple)):
        return ' '.join(str(x) for x in cmd)
    else:
        return cmd


def subprocess_run(cmd, *, skip_frames=0, **kwargs):
    """
    A simple wrapper for the real subprocess.run() that logs the command used.
    """
    # when logging, skip current stack frame - report the place we were called
    # from, not util.subprocess_run itself
    util.log(f'running: {_format_subprocess_cmd(cmd)}', skip_frames=skip_frames+1)
    return subprocess.run(cmd, **kwargs)


def subprocess_Popen(cmd, *, skip_frames=0, **kwargs):  # noqa: N802
    """
    A simple wrapper for the real subprocess.Popen() that logs the command used.
    """
    util.log(f'running: {_format_subprocess_cmd(cmd)}', skip_frames=skip_frames+1)
    return subprocess.Popen(cmd, **kwargs)


def subprocess_stream(cmd, *, check=False, skip_frames=0, **kwargs):
    """
    Run 'cmd' via subprocess.Popen() and return an iterator over any lines
    the command outputs on stdout, in text mode.

    With 'check' set to True, raise a CalledProcessError if the 'cmd' failed.

    To capture both stdout and stderr as yielded lines, use subprocess.STDOUT.
    """
    util.log(f'running: {_format_subprocess_cmd(cmd)}', skip_frames=skip_frames+1)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, **kwargs)

    def generate_lines():
        for line in proc.stdout:
            yield line.rstrip('\n')
        code = proc.wait()
        if code > 0 and check:
            raise subprocess.CalledProcessError(cmd=cmd, returncode=code)

    return (proc, generate_lines())

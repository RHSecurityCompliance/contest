import select
import subprocess

from lib import util


class VerboseCalledProcessError(subprocess.CalledProcessError):
    """
    A CalledProcessError that includes captured stderr in its string representation.
    """
    def __str__(self):
        base = super().__str__()
        if self.stderr:
            stderr_output = self.stderr
            if isinstance(stderr_output, bytes):
                stderr_output = stderr_output.decode(errors='replace')
            # truncate very long stderr to keep error messages readable
            max_len = 2000
            if len(stderr_output) > max_len:
                stderr_output = stderr_output[:max_len] + '\n... (truncated)'
            return f"{base} \nCaptured stderr: \n{stderr_output}"
        return base

    def __repr__(self):
        return self.__str__()


def _format_subprocess_cmd(cmd):
    if isinstance(cmd, (list, tuple)):
        return ' '.join(str(x) for x in cmd)
    else:
        return cmd


def subprocess_run(cmd, *, check=False, skip_frames=0, stderr=None, **kwargs):
    """
    A simple wrapper for the real subprocess.run() that logs the command used.

    When stderr=subprocess.PIPE and check=True, automatically converts
    CalledProcessError to VerboseCalledProcessError with captured stderr details.
    """
    # when logging, skip current stack frame - report the place we were called
    # from, not util.subprocess_run itself
    util.log(f'running: {_format_subprocess_cmd(cmd)}', skip_frames=skip_frames+1)

    use_verbose_errors = (stderr is subprocess.PIPE and check)

    try:
        return subprocess.run(cmd, stderr=stderr, **kwargs)
    except subprocess.CalledProcessError as e:
        if use_verbose_errors and e.stderr is not None:
            # re-raise as VerboseCalledProcessError with stderr details
            raise VerboseCalledProcessError(
                returncode=e.returncode,
                cmd=e.cmd,
                stdout=e.output,
                stderr=e.stderr,
            ) from e
        else:
            # re-raise the original CalledProcessError exception
            raise


def subprocess_Popen(cmd, *, skip_frames=0, **kwargs):  # noqa: N802
    """
    A simple wrapper for the real subprocess.Popen() that logs the command used.
    """
    util.log(f'running: {_format_subprocess_cmd(cmd)}', skip_frames=skip_frames+1)
    return subprocess.Popen(cmd, **kwargs)


def subprocess_stream(cmd, *, check=False, skip_frames=0, stderr=None, **kwargs):
    """
    Run 'cmd' via subprocess.Popen() and return an iterator over any lines
    the command outputs on stdout, in text mode.

    When stderr=subprocess.PIPE and check=True, automatically converts
    CalledProcessError to VerboseCalledProcessError with captured stderr details.

    To capture both stdout and stderr as yielded lines, use stderr=subprocess.STDOUT.
    """
    util.log(f'running: {_format_subprocess_cmd(cmd)}', skip_frames=skip_frames+1)

    use_verbose_errors = (stderr is subprocess.PIPE and check)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=stderr, text=True, **kwargs)

    def generate_lines():
        stderr_output = None
        for line in proc.stdout:
            yield line.rstrip('\n')

        # if capturing stderr separately, try to read it now
        if use_verbose_errors and proc.stderr:
            rlist, _, _ = select.select([proc.stderr], [], [], 0.001)
            if rlist:
                stderr_output = proc.stderr.read()

        code = proc.wait()
        if code > 0 and check:
            if use_verbose_errors and stderr_output is not None:
                raise VerboseCalledProcessError(
                    returncode=code,
                    cmd=cmd,
                    stderr=stderr_output,
                )
            else:
                raise subprocess.CalledProcessError(cmd=cmd, returncode=code)

    return (proc, generate_lines())

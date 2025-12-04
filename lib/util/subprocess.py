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
        return subprocess.run(cmd, check=check, stderr=stderr, **kwargs)
    except subprocess.CalledProcessError as e:
        if use_verbose_errors and e.stderr is not None:
            # re-raise as VerboseCalledProcessError with stderr details
            raise VerboseCalledProcessError(
                returncode=e.returncode,
                cmd=e.cmd,
                output=e.output,
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
        stdout_buffer = ''
        stderr_buffer = ''

        streams = [proc.stdout]
        if use_verbose_errors and proc.stderr:
            streams.append(proc.stderr)

        # read from stdout and stderr as data becomes available
        while streams:
            rlist, _, _ = select.select(streams, [], [])

            for stream in rlist:
                chunk = stream.read(4096)
                if not chunk:  # EOF on this stream
                    streams.remove(stream)
                    continue

                if stream == proc.stdout:
                    stdout_buffer += chunk
                    while '\n' in stdout_buffer:
                        line, stdout_buffer = stdout_buffer.split('\n', 1)
                        yield line
                elif stream == proc.stderr:
                    stderr_buffer += chunk

        # yield any remaining content in stdout buffer
        if stdout_buffer:
            yield stdout_buffer

        code = proc.wait()
        if code > 0 and check:
            if use_verbose_errors and stderr_buffer:
                raise VerboseCalledProcessError(
                    returncode=code,
                    cmd=cmd,
                    stderr=stderr_buffer,
                )
            else:
                raise subprocess.CalledProcessError(cmd=cmd, returncode=code)

    return (proc, generate_lines())

import os
import select
import subprocess

from lib import util, versions


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
    util.log(f'running: {_format_subprocess_cmd(cmd)}', skip_frames=1)
    return subprocess.run(cmd, **kwargs)


def subprocess_Popen(cmd, **kwargs):
    """
    A simple wrapper for the real subprocess.Popen() that logs the command used.
    """
    util.log(f'running: {_format_subprocess_cmd(cmd)}', skip_frames=1)
    return subprocess.Popen(cmd, **kwargs)


def subprocess_stream(cmd, check=False, **kwargs):
    """
    Run 'cmd' via subprocess.Popen() and return an iterator over any lines
    the command outputs on stdout, in text mode.

    With 'check' set to True, raise a CalledProcessError if the 'cmd' failed.

    To capture both stdout and stderr as yielded lines, use subprocess.STDOUT.
    """
    util.log(f'running: {_format_subprocess_cmd(cmd)}', skip_frames=1)
    if versions.rhel == 7 and 'stderr' in kwargs and kwargs['stderr'] == subprocess.STDOUT:
        return _subprocess_stream_rhel7(cmd, check, **kwargs)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True, **kwargs)

    def generate_lines():
        for line in proc.stdout:
            yield line.rstrip('\n')
        code = proc.wait()
        if code > 0 and check:
            raise subprocess.CalledProcessError(cmd=cmd, returncode=code)

    return (proc, generate_lines())


# RHEL-7 only hack
#
# The problem is that old RHEL-7 oscap scanner version interleaves stdout and
# stderr by writing a portion of stdout, then stderr, then finishing stdout.
#
# This leads to interleaved --progress output with errors like so:
#
#   xccdf_org.ssgproject.content_rule_some_rule_name:W: oscap: Obtrusive data from probe!
#   W: oscap:       Obtrusive data from probe!
#   W: oscap:       Obtrusive data from probe!
#   fail
#
# This is caused by
#   1) oscap printing the rule name and ':' in one stdout write() call,
#   2) handling errors/warnings and printing them on stderr,
#   3) finishing rule code and printing status ('fail') on stdout
#
# This is fine for reading stdout/stderr separately, but combining them leads
# to the mess above.
#
# The code below works around this by reading stdout and stderr into separate
# buffers, and checking if there's a newline character in any of them
# - if it's found, a full line is printed from that buffer.
#
# As a result, this avoids printing partial lines without a newline, such as the
# rule name with ':' in the example, waiting for the 'fail\n' to arrive into
# the buffer and then yielding the full line.
#
def _subprocess_stream_rhel7(cmd, check=False, **kwargs):
    kwargs['stdout'] = subprocess.PIPE
    kwargs['stderr'] = subprocess.PIPE
    proc = subprocess.Popen(cmd, universal_newlines=True, **kwargs)

    files = set()
    for f in [proc.stdout, proc.stderr]:
        if f:
            os.set_blocking(f.fileno(), False)
            files.add(f)

    buffers = dict.fromkeys(files, '')

    def generate_lines():
        while files:
            fds = [x.fileno() for x in files]
            read_events, _, _ = select.select(fds, [], [], 0)
            for fileno in read_events:
                # second hashmap would be better, but this is temp code, meh
                f = next(x for x in files if x.fileno() == fileno)
                data = f.read()
                if len(data) == 0:
                    files.remove(f)
                else:
                    buffers[f] += data
            for f, buffer in buffers.items():
                while '\n' in buffer:
                    line, _, buffer = buffer.partition('\n')
                    yield line
                buffers[f] = buffer
        code = proc.wait()
        if code > 0 and check:
            raise subprocess.CalledProcessError(cmd=cmd, returncode=code)

    return (proc, generate_lines())

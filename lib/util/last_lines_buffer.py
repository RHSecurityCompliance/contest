#!/usr/bin/python3

import os
import threading
import collections


class LastLinesBuffer:
    """
    An in-memory buffer for keeping the last N lines of a program's output.

    Useful when launching very verbose programs via subprocess.run() but still
    wanting to keep the last ie. 100 lines for error logging when that process
    returns non-zero exit code.

        with LastLinesBuffer(100) as buff:
            proc = subprocess.run(['verbose_cmd'], stdout=buff, text=True)

        if proc.returncode != 0:
            print(buff.output)
            proc.check_returncode()

    Do not rely on '.output' being complete before the context manager ends,
    access it afterwards.
    """

    def __init__(self, max_lines):
        """
        Specify 'max_lines' as maximum lines of output to keep.
        """
        self.text = None
        self.max_lines = max_lines
        self._lines = collections.deque(maxlen=max_lines)
        self.pipe_r = self.pipe_w = None

    def _line_reader(self, fobj):
        for line in fobj:
            self._lines.append(line)

    def __enter__(self):
        (self.pipe_r, self.pipe_w) = os.pipe()
        # create a python file object, because we're too lazy to implement
        # .readline() buffering ourselves
        self._pipe_r_fobj = os.fdopen(self.pipe_r)
        t = threading.Thread(target=self._line_reader, args=(self._pipe_r_fobj,))
        self.thread = t
        t.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        os.close(self.pipe_w)
        self.pipe_w = None
        self.thread.join()
        # this will also close the self.pipe_r file descriptor
        self._pipe_r_fobj.close()
        self.pipe_r = None

    def fileno(self):
        """
        Return a file descriptor (as integer), opened for writing.
        """
        return self.pipe_w

    @property
    def output(self):
        """
        Return the captured lines as a str, with the last newline included.
        """
        return ''.join(self._lines)

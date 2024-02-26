import sys
import inspect
from pathlib import Path
from datetime import datetime


def log(msg, *, skip_frames=0):
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

    With 'skip_frames' > 0, report module or function that called the function
    which called log(), rather than the function which called log(). This is
    useful for lightweight wrappers, as the call of the wrapper gets logged,
    rather than log() inside the wrapper.
    A value of 1 skips one stack frame, value of 2 skips 2 frames, etc.,
    not counting the log() function itself.
    """
    stack = inspect.stack()
    if len(stack)-1 <= skip_frames:
        raise SyntaxError("skip_frames exceeds call stack (frame count)")
    stack = stack[skip_frames+1:]

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

    # if the function has 'self' and it looks like a class (instance),
    # prepend it to the function name
    p_locals = parent.frame.f_locals
    if 'self' in p_locals:
        self = p_locals['self']
        if hasattr(self, '__class__') and inspect.isclass(self.__class__):
            name = self.__name__ if isinstance(self, type) else self.__class__.__name__
            function = f'{name}.{function}'

    # don't report module name of a function if it's the same as running module
    if parent.filename != module.filename:
        parent_modname = parent.frame.f_globals['__name__']
        log_prefix += f': {parent_modname}.{function}:{parent.lineno}'
    elif parent.function != '<module>':
        log_prefix += f': {function}:{parent.lineno}'

    sys.stdout.write(f'{log_prefix}: {msg}\n')
    sys.stdout.flush()

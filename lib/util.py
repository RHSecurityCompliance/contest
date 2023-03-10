import os
import inspect
import logging
import contextlib
from pathlib import Path

# directory with all these modules, and potentially more files
# - useful until TMT can parametrize 'environment:' with variable expressions,
#   so we could add the libdir to PATH and PYTHONPATH
libdir = Path(inspect.getfile(inspect.currentframe())).parent


class AutoCleanup(contextlib.AbstractContextManager):
    """
    Base class for making cleanup-aware classes.

    It provides an '.atexit()' method, which works like the 'atexit' module
    and its 'atexit.register()' function, except that the registered function
    is called on context manager __exit__.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__cleanup_buff = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        while self.__cleanup_buff:
            func, args, kwargs = self.__cleanup_buff.pop()
            func(*args, **kwargs)

    def atexit(self, func, *args, **kwargs):
        self.__cleanup_buff.append((func, args, kwargs))


def setup_test_logging(level=logging.DEBUG):
    logging.basicConfig(level=level,
                        format='%(asctime)s %(name)s:%(funcName)s:%(lineno)d: %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')
    #logging.addLevelName(logging.DEBUG, 'D')
    #logging.addLevelName(logging.INFO, 'I')
    #logging.addLevelName(logging.ERROR, 'E')

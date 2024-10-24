"""
Provides utilities and wrappers for creating and manipulating images and
containers using the 'podman' utility.
"""

from lib import util


def podman(*args, **kwargs):
    """
    A simple wrapper for the podman(1) CLI, passing python arguments
    as shell arguments.
    """
    # TODO: make subprocess_run able to pass skip_frames to underlying calls,
    #       and use it here, to print out our caller, not podman.podman()
    util.subprocess_run(['podman', *args], check=True, universal_newlines=True, **kwargs)

"""
Simple recursive backup/restore of filesystem paths, preserving
file metadata where possible.
"""

import shutil
import contextlib
from pathlib import Path

from lib import util


def backup(path):
    util.log(f"backing up {path}", skip_frames=1)
    path = Path(path)
    path_backup = path.with_suffix('.contest-backup')
    if path_backup.exists():
        raise RuntimeError(f"previous backup found: {path_backup}")
    # store the original files in the backup + copy them for our use
    # - this is to preserve original inode numbers after restore
    path.rename(path_backup)
    shutil.copytree(path_backup, path, symlinks=True)


def restore(path):
    util.log(f"restoring {path}", skip_frames=1)
    path = Path(path)
    path_backup = path.with_suffix('.contest-backup')
    if not path_backup.exists():
        raise RuntimeError(f"no backup found: {path_backup}")
    shutil.rmtree(path)
    path_backup.rename(path)


@contextlib.contextmanager
def backed_up(path):
    """
    Context manager for automatic backup/restore of a given path,
    use as:
        with backed_up('/some/path'):
            # do destructive stuff to it
    """
    backup(path)
    yield
    restore(path)

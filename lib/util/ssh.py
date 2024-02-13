import subprocess

from lib import util


def ssh_keygen(path):
    """Generate private/public keys prefixed by 'path'."""
    cmd = ['ssh-keygen', '-N', '', '-f', path]
    util.subprocess_run(cmd, stdout=subprocess.DEVNULL, check=True)

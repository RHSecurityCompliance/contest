import subprocess

from .subprocess import subprocess_run

def ssh_keygen(path):
    """Generate private/public keys prefixed by 'path'."""
    subprocess_run(['ssh-keygen', '-N', '', '-f', path], stdout=subprocess.DEVNULL, check=True)

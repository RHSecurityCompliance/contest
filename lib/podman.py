"""
Provides utilities and wrappers for creating and manipulating images and
containers using the 'podman' utility.
"""

import re
import time
import textwrap
import subprocess
from pathlib import Path

from lib import util


def podman(*args, log=True, check=True, **kwargs):
    """
    A simple wrapper for the podman(1) CLI, passing python arguments
    as shell arguments.
    """
    if log:
        run = util.subprocess_run
        kwargs['skip_frames'] = 1
    else:
        run = subprocess.run

    return run(
        ['podman', *args],
        check=check, universal_newlines=True,
        **kwargs,
    )


class Containerfile:
    def __init__(self, contents=''):
        self.contents = contents

    def __repr__(self):
        return self.contents

    def __str__(self):
        return self.contents

    def __add__(self, other):
        new = '\n'.join((self.contents, other)) if self.contents else other
        return __class__(new)

    def add_ssh_pubkey(self, key, user='root'):
        home = '/root' if user == 'root' else f'/home/{user}'
        self.contents += '\n' + util.dedent(fr'''
            # ssh key for {user} in {home}
            RUN mkdir -p -m 0700 '{home}/.ssh'
            RUN echo '{key}' >> '{home}/.ssh/authorized_keys'
            RUN chmod 0600 '{home}/.ssh/authorized_keys'
            RUN chown {user}:{user} -R '{home}/.ssh'
        ''')

    def write_to(self, path):
        util.log(f"writing to {path}:\n{textwrap.indent(self.contents, '    ')}")
        Path(path).write_text(self.contents)


class Registry:
    """
    Local podman registry as a class (instance).

    with Registry() as reg:
        # pull docker.io/foobar, push it to the local registry
        local_image = reg.push('docker.io/foobar')
        # push a locally-built image foobar to the local registry
        local_image = reg.push('foobar')
        # local_image is ie. '127.0.0.1:12345/foobar'
        ...
    """
    def __init__(self, name='contest-registry', host_addr='127.0.0.1'):
        self.name = name
        self.addr = host_addr
        self.proc = None
        self.tagged = set()

    def start(self):
        util.log(f"starting container for {self.name}")
        proc = util.subprocess_Popen([
            'podman', 'container', 'run', '--rm', '--name', self.name,
            '--publish', f'{self.addr}::5000', 'registry:2',
        ])
        self.proc = proc
        try:
            # wait for the registry server to start existing
            for _ in range(100):
                proc = podman('container', 'exists', self.name, check=False, log=False)
                if proc.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError("registry container failed creation")
            # wait for it to start up
            podman('container', 'wait', '--condition=running', self.name)
            # wait for it to start responding on TCP
            host, port = self.get_listen_addr()
            util.wait_for_tcp(host, port)
        except Exception as e:
            # make sure we always clean up
            proc.terminate()
            raise e from None

    def stop(self):
        if self.proc:
            util.log(f"stopping container for {self.name}")
            self.proc.terminate()
            self.proc.wait()

    def get_listen_addr(self):
        """
        Returns an (address, port) tuple the started-up registry is listening on.
        """
        proc = podman('container', 'port', self.name, stdout=subprocess.PIPE)
        portmap = proc.stdout.rstrip('\n')
        match = re.fullmatch(r'[0-9]+/tcp -> ([^:]+):([0-9]+)', portmap)
        if not match:
            raise RuntimeError(f"could not parse port mapping from: {portmap}")
        host, port = match.groups()
        return (host, int(port))

    def push(self, image):
        """
        Given an image name/url, tag that image with a local registry addr:port
        and push to the local started-up registry.

        Returns image path on the local registry.
        """
        # path after the first / (if specified as an URL),
        # or just the image name if given as a plain name
        _, _, sub_path = image.partition('/')
        if not sub_path:
            sub_path = image

        addr, port = self.get_listen_addr()
        full_local_path = f'{addr}:{port}/{sub_path}'

        podman('image', 'tag', image, full_local_path)
        self.tagged.add(full_local_path)
        podman('image', 'push', '--tls-verify=false', full_local_path)

        return full_local_path

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()
        for tag in self.tagged:
            podman('image', 'untag', tag)

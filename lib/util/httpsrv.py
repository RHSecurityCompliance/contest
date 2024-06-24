"""
Simple HTTP server implementation that allows adding arbitrary paths,
backed by (different) filesystem paths.

Ie.
    srv = BackgroundHTTPServer('127.0.0.1', 8080)
    srv.add_file('/on/disk/file.txt', '/visible.txt')
    srv.add_file('/on/disk/dir', '/somedir')
    with srv:
        ...

Any HTTP GET requests for '/visible.txt' will receive the contents of
'/on/disk/file.txt' (or 404).

Any HTTP GET requests for '/somedir/aa/bb' will receive the contents of
'/on/disk/dir/aa/bb' (or 404).

Port can also be specified as 0 (just like for Python's socketserver)
which will cause a random unused port to be allocated by the OS kernel.
You can then retrieve it from server_address (just like socketserver):

    srv = BackgroundHTTPServer('127.0.0.1', 0)
    with srv:
        host, port = srv.server.server_address
        # 'port' here will be >0
"""

import shutil
import subprocess
import threading
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

from lib import util


class _BackgroundHTTPServerHandler(SimpleHTTPRequestHandler):
    def send_file(self, path):
        try:
            with open(path, 'rb') as f:
                self.send_response(200)
                self.end_headers()
                shutil.copyfileobj(f, self.wfile)
        except (FileNotFoundError, NotADirectoryError):
            self.send_response(404)
            self.end_headers()
        except (PermissionError, IsADirectoryError):
            self.send_response(403)
            self.end_headers()

    def do_GET(self):
        file_map = self.server.file_mapping
        dir_map = self.server.dir_mapping
        get_path = Path(self.path).relative_to('/')
        # try a file path match first
        for url_path, fs_path in file_map.items():
            if get_path == url_path:
                self.send_file(fs_path)
                return
        # try a directory prefix
        for url_path, fs_path in dir_map.items():
            # if 'prefix/dir' in GET /prefix/dir/some/path
            if url_path in get_path.parents:
                path_within_dir = get_path.relative_to(url_path)
                self.send_file(fs_path / path_within_dir)
                return
        # unknown path requested via GET
        self.send_response(404)
        self.end_headers()

    def log_message(self, form, *args):
        addr, port = self.server.server_address
        util.log(f'{addr}:{port}: ' + form % args)


class BackgroundHTTPServer:
    def __init__(self, host, port):
        self.file_mapping = {}
        self.dir_mapping = {}
        self.requested_address = (host, port)
        self.firewalld_zones = []

    def add_file(self, fs_path, url_path=None):
        """
        Map a filesystem path to a file to virtual location on the HTTP server,
        so that requests to the virtual location get the contents of the real
        file on the filesystem.

        'fs_path' can be relative or absolute,
        'url_path' can have an optional leading '/' that is automatically ignored

        For example:
            # GET /users will receive contents of /etc/passwd
            .add_file('/etc/passwd', 'users')
            # GET /some/file will get contents of tmpfile (relative to CWD)
            .add_file('tmpfile', 'some/file')
            # GET /testfile will get the contents of testfile (in CWD)
            .add_file('testfile')
        """
        url_path = Path(fs_path) if url_path is None else Path(url_path.lstrip('/'))
        self.file_mapping[url_path] = Path(fs_path)

    def add_dir(self, fs_path, url_path=None):
        """
        Map a filesystem directory to a virtual location on the HTTP server,
        see add_file() for details.

        For example:
            # GET /config/passwd will receive the contents of /etc/passwd
            .add_dir('/etc', 'config')
            # GET /repo/repodata/repomd.xml gets /tmp/tmp.12345/repodata/repomd.xml
            .add_dir('/tmp/tmp.12345', 'repo')
            # GET /testdir/123 will get the contents of testdir/123 (in CWD)
            .add_dir('testdir')
        """
        url_path = Path(fs_path) if url_path is None else Path(url_path.lstrip('/'))
        self.dir_mapping[url_path] = Path(fs_path)

    def __enter__(self):
        server = HTTPServer(self.requested_address, _BackgroundHTTPServerHandler)

        host, port = server.server_address
        util.log(f"starting: {host}:{port}")

        util.log(f"using file mapping: {self.file_mapping}")
        util.log(f"using dir mapping: {self.dir_mapping}")
        server.file_mapping = self.file_mapping
        server.dir_mapping = self.dir_mapping

        # allow the target port on the firewall
        if shutil.which('firewall-cmd'):
            res = util.subprocess_run(
                ['firewall-cmd', '--state'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                res = util.subprocess_run(
                    ['firewall-cmd', '--get-zones'], stdout=subprocess.PIPE,
                    universal_newlines=True, check=True)
                self.firewalld_zones = res.stdout.strip().split(' ')
                for zone in self.firewalld_zones:
                    util.subprocess_run(
                        ['firewall-cmd', f'--zone={zone}', f'--add-port={port}/tcp'],
                        stdout=subprocess.DEVNULL, check=True)

        self.server = server
        self.thread = threading.Thread(target=server.serve_forever)
        self.thread.start()

    def __exit__(self, exc_type, exc_value, traceback):
        host, port = self.server.server_address
        util.log(f"ending: {host}:{port}")

        self.server.shutdown()
        self.thread.join()
        self.server.socket.close()

        # remove allow rules from the firewall
        for zone in self.firewalld_zones:
            util.subprocess_run(
                ['firewall-cmd', f'--zone={zone}', f'--remove-port={port}/tcp'],
                stdout=subprocess.DEVNULL, check=True)

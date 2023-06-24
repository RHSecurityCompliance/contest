import shutil
import subprocess
import multiprocessing
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

from lib import util


class _BackgroundHTTPServerHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        mapping = self.server.file_mapping
        if self.path not in mapping:
            self.send_response(404)
            self.end_headers()
            return
        with open(mapping[self.path], 'rb') as f:
            self.send_response(200)
            self.end_headers()
            shutil.copyfileobj(f, self.wfile)

    def log_message(self, form, *args):
        util.log(form % args)


class BackgroundHTTPServer(HTTPServer):
    def __init__(self, host, port):
        self.file_mapping = {}
        self.listen_port = port
        self.firewalld_zones = []
        super().__init__((host, port), _BackgroundHTTPServerHandler)

    def add_file(self, fspath, urlpath=None):
        if not urlpath:
            urlpath = Path(fspath).name
        self.file_mapping[f'/{urlpath}'] = fspath

    def __enter__(self):
        util.log(f"starting with: {self.file_mapping}")
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
                        ['firewall-cmd', f'--zone={zone}', f'--add-port={self.listen_port}/tcp'],
                        stdout=subprocess.DEVNULL, check=True)
        proc = multiprocessing.Process(target=self.serve_forever)
        self.process = proc
        proc.start()

    def __exit__(self, exc_type, exc_value, traceback):
        util.log("ending")
        self.process.terminate()
        self.process.join()
        # remove allow rules from the firewall
        for zone in self.firewalld_zones:
            util.subprocess_run(
                ['firewall-cmd', f'--zone={zone}', f'--remove-port={self.listen_port}/tcp'],
                stdout=subprocess.DEVNULL, check=True)

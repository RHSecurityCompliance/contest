import hashlib
import shutil

import requests
import urllib3

from lib import util


def download(url, dest, *, sha256=None):
    """
    Download 'url' over HTTP(S) to a local file path 'dest', retrying
    on connection errors.

    If 'sha256' is given (as a hex string), verify the downloaded file
    against it, raising RuntimeError on a mismatch.
    """
    util.log(f"downloading {url} to {dest}")
    session = requests.Session()
    retries = urllib3.util.Retry(total=10, backoff_factor=0.1)
    adapter = requests.adapters.HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    with session.get(url, stream=True) as reply:
        reply.raise_for_status()
        # undo any HTTP Content-Encoding (ie. gzip), like requests does
        # for non-raw access
        reply.raw.decode_content = True
        with open(dest, "wb") as f:
            shutil.copyfileobj(reply.raw, f)

    if sha256:
        with open(dest, "rb") as f:
            actual = hashlib.file_digest(f, "sha256").hexdigest()
        if actual != sha256:
            raise RuntimeError(f"sha256 mismatch for {url}: expected {sha256}, got {actual}")

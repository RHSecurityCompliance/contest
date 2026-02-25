#!/usr/bin/python3

import re
import subprocess

from lib import util, results


url_regex = re.compile(r'href=[\'"]?(http[^\'" ]+)', re.IGNORECASE)

with open(util.get_datastream()) as ds:
    ds_content = ds.read()
    urls = set(url_regex.findall(ds_content))

for url in urls:
    # log the URL in case we hit an anti-bot detection that spams the client
    # with GBs of data, causing a test timeout and the URL to never otherwise
    # be reported (because the result doesn't get reported)
    util.log(f"trying url: {url}")

    proc = subprocess.run(
        ["curl", "--retry", "10", "-sSfL", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        results.report('fail', url, proc.stderr.rstrip('\n'))
    else:
        results.report('pass', url)

results.report_and_exit()

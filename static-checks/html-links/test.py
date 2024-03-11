#!/usr/bin/python3

import re
import requests

from lib import util, results


headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64;)'}
url_regex = re.compile(r'href=[\'"]?(http[^\'" ]+)', re.IGNORECASE)

with open(util.get_datastream(), 'r') as ds:
    ds_content = ds.read()
    urls = set(url_regex.findall(ds_content))

for url in urls:
    try:
        r = requests.get(url, timeout=10, headers=headers)
        r.raise_for_status()
    except requests.exceptions.RequestException as err:
        results.report('fail', url, err)
    else:
        results.report('pass', url)

results.report_and_exit()

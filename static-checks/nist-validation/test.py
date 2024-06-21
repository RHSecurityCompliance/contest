#!/usr/bin/python3

import os
import io
import zipfile
import requests
import subprocess

from lib import util, results


url = 'https://github.com/RHSecurityCompliance/contest-data/raw/main/data/scapval-1.3.6-rc3.zip'
r = requests.get(url)
r.raise_for_status()
zip = zipfile.ZipFile(io.BytesIO(r.content))
zip.extractall()
os.chmod('scapval.sh', 0o755)

for datastream in util.iter_datastreams():
    ds_name = datastream.stem
    report_file = f'{ds_name}.report.html'
    result_file = f'{ds_name}.results.xml'
    cmd = [
        './scapval.sh',
        '-scapversion', '1.3',
        '-valreportfile', report_file,
        '-valresultfile', result_file,
        '-file', datastream,
    ]
    proc = util.subprocess_run(cmd, stdout=subprocess.PIPE, check=True, universal_newlines=True)
    if 'The target is valid' in proc.stdout:
        results.report('pass', ds_name)
    elif 'The target is invalid' in proc.stdout:
        results.report('fail', ds_name, logs=[report_file, result_file])
    else:
        raise RuntimeError("SCAPval out has not been correctly parsed")

results.report_and_exit()

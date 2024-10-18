#!/usr/bin/python3

import os
import io
import zipfile
import requests
import subprocess
import xml.etree.ElementTree as ET

from lib import util, results


url = 'https://github.com/RHSecurityCompliance/contest-data/raw/main/data/scapval-1.3.6-rc3.zip'
r = requests.get(url)
r.raise_for_status()
zip = zipfile.ZipFile(io.BytesIO(r.content))
zip.extractall()
os.chmod('scapval.sh', 0o755)

ns = {'nist': 'http://csrc.nist.gov/ns/decima/results/1.0'}

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
    util.subprocess_run(cmd, stdout=subprocess.DEVNULL, check=True)
    tree = ET.parse(result_file)
    root = tree.getroot()
    for elem in root.findall('./nist:results/nist:base-requirement', ns):
        name = f'{ds_name}/{elem.attrib["id"]}'
        status = elem.find('./nist:status', ns).text
        if status in ['NOT_TESTED', 'NOT_APPLICABLE']:
            continue
        elif status in ['PASS', 'WARNING', 'INFORMATIONAL']:
            results.report('pass', name)
        elif status == 'FAIL':
            results.report('fail', name, logs=[report_file, result_file])
        else:
            results.report('error', name, logs=[report_file, result_file])

results.report_and_exit()

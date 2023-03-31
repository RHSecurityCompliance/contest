#!/usr/bin/python3

import os
import sys
import atexit
from logging import info as log

sys.path.insert(0, '../../lib')
import util
import tmt


util.setup_test_logging()

import virt

virt.setup_host()

g = virt.Guest('minimal_with_oscap')

if not g.can_be_snapshotted():
    g.install()
    g.prepare_for_snapshot()

import time
import shutil

rhel=8

with g.snapshotted():
    prof = os.environ['PROFILE']
    ret = g.ssh(f'oscap xccdf eval --profile {prof} --progress --remediate /usr/share/xml/scap/ssg/content/ssg-rhel{rhel}-ds.xml ; chage -d 99999 root')
    log(f'oscap returned: {ret.returncode}')
    g.soft_reboot()
    ret = g.ssh(f'oscap xccdf eval --profile {prof} --progress --report report.html /usr/share/xml/scap/ssg/content/ssg-rhel{rhel}-ds.xml')
    log(f'oscap returned: {ret.returncode}')
    g.ssh('chmod 0644 report.html')
    g.copy_from('report.html')
    datadir = os.environ['TMT_TEST_DATA']
    shutil.move('report.html', f'{datadir}/{prof}-report.html')

tmt.report('pass')

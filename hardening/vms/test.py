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

g = virt.Guest(virt.GUEST_NAME_GUI)

if not g.can_be_snapshotted():
    g.install()
    g.prepare_for_snapshot()

import time
import shutil

rhel=8

with g.snapshotted():
    prof = os.environ['PROFILE']
    ret = g.comm_out('oscap', 'xccdf', 'eval', '--profile', prof, '--progress', '--remediate', f'/usr/share/xml/scap/ssg/content/ssg-rhel{rhel}-ds.xml')
    log(f'oscap returned: {ret.returncode}')
    #time.sleep(600)
    g.soft_reboot()
    g.comm_out('oscap', 'xccdf', 'eval', '--profile', prof, '--progress', '--report', f'{prof}-report.html', f'/usr/share/xml/scap/ssg/content/ssg-rhel{rhel}-ds.xml')
    #ret = g.comm(['oscap', 'xccdf', 'eval', '--profile', prof, '--progress', '--remediate', '--report', f'{prof}-report.html', '/usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml'])
    #log(f'oscap returned: {ret.returncode}')
    g.comm_out('chmod', '0644', f'{prof}-report.html')
    g.copy_from(f'{prof}-report.html')
    datadir = os.environ['TMT_TEST_DATA']
    shutil.move(f'{prof}-report.html', f'{datadir}/{prof}-report.html')

#with g.snapshotted():
    #state = g.comm(['ls', '/', '-l'])
    #log(state.stdout)
    #g.comm(['mkdir', 'foob'])
    #g.copy_to('passwd', 'foob/dasswd')
    #out = g.comm(['cat', 'foob/dasswd'])
    #log(out)

tmt.report('pass')

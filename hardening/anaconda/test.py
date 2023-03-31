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

ks = virt.Kickstart()

prof = os.environ['PROFILE']
oscap_conf = {
    #'content-type': 'rpm',
    'content-type': 'scap-security-guide',
    'profile': prof,
}

if prof.endswith('_gui'):
    ks.add_packages(['@Server with GUI'])

ks.add_oscap(oscap_conf)

ks.add_post('chage -d 99999 root')

g.install(kickstart=ks)

import time
import shutil

rhel=8

with g.booted():
    ret = g.ssh(f'oscap xccdf eval --profile {prof} --progress --report report.html /usr/share/xml/scap/ssg/content/ssg-rhel{rhel}-ds.xml')
    log(f'oscap returned: {ret.returncode}')
    g.ssh('chmod 0644 report.html')
    g.copy_from('report.html')
    datadir = os.environ['TMT_TEST_DATA']
    shutil.move('report.html', f'{datadir}/report.html')

tmt.report('pass')

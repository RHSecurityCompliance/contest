#!/usr/bin/python3

import os
import sys
import atexit
from logging import info as log

import util
import tmt
import virt
from versions import rhel


virt.setup_host()

g = virt.Guest('minimal_with_oscap')

prof = os.environ['PROFILE']
prof = f'xccdf_org.ssgproject.content_profile_{prof}'

if not g.can_be_snapshotted():
    ks = virt.Kickstart()
    if prof.endswith('_gui'):
        if rhel < 8:
            ks.add_packages(['@^Server with GUI'])
        else:
            ks.add_packages(['@Server with GUI'])
    g.install(kickstart=ks)
    g.prepare_for_snapshot()

import time
import shutil

ds = f'/usr/share/xml/scap/ssg/content/ssg-rhel{rhel.major}-ds.xml'

with g.snapshotted():
    ret = g.ssh(f'oscap xccdf eval --profile {prof} --progress --remediate {ds} ; chage -d 99999 root')
    log(f'oscap returned: {ret.returncode}')
    g.soft_reboot()
    ret = g.ssh(f'oscap xccdf eval --profile {prof} --progress --report report.html {ds}')
    log(f'oscap returned: {ret.returncode}')
    g.ssh('chmod 0644 report.html')
    g.copy_from('report.html')
    datadir = os.environ['TMT_TEST_DATA']
    shutil.move('report.html', f'{datadir}/report.html')

tmt.report('pass')

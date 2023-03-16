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

vm = virt.Guest(virt.GUEST_NAME_GUI)

if not vm.can_be_snapshotted():
    vm.install()
    vm.prepare_for_snapshot()

import shutil

with vm.snapshotted():
    prof = os.environ['PROFILE']
    ret = vm.comm_out('sudo', 'oscap', 'xccdf', 'eval', '--profile', prof, '--progress', '--remediate', '/usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml')
    #log(f'oscap returned: {ret.returncode}')
    vm.soft_reboot()
    vm.comm_out('sudo', 'oscap', 'xccdf', 'eval', '--profile', prof, '--progress', '--report', f'{prof}-report.html', '/usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml')
    #ret = vm.comm(['oscap', 'xccdf', 'eval', '--profile', prof, '--progress', '--remediate', '--report', f'{prof}-report.html', '/usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml'])
    #log(f'oscap returned: {ret.returncode}')
    vm.comm_out('sudo', 'chmod', '0644', f'{prof}-report.html')
    vm.copy_from(f'{prof}-report.html')
    datadir = os.environ['TMT_TEST_DATA']
    shutil.move(f'{prof}-report.html', f'{datadir}/{prof}-report.html')

#with vm.snapshotted():
    #state = vm.comm(['ls', '/', '-l'])
    #log(state.stdout)
    #vm.comm(['mkdir', 'foob'])
    #vm.copy_to('passwd', 'foob/dasswd')
    #out = vm.comm(['cat', 'foob/dasswd'])
    #log(out)

tmt.report('pass')

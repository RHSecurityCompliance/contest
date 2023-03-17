#!/usr/bin/python3

import os
import sys
import time
import atexit
from logging import info as log

sys.path.insert(0, '../lib')
import util
import tmt


util.setup_test_logging()
# TODO:
#atexit.register(tmt.pass_on_success)

log("hello from test!")

#import requests
#x = requests.get('https://google.com')
#log(f"got req: {x}")


tmt.report('pass', '/some/result')

tmt.report('fail', '/another/result', logs=['/etc/passwd', '/etc/mtab'], note='foo \'"bar')


import virt

virt.setup_host()

vm = virt.Guest(virt.GUEST_NAME_GUI)

#vm.install()
#vm.prepare_for_snapshot()
if not vm.can_be_snapshotted():
    vm.install()
    vm.prepare_for_snapshot()

with vm.snapshotted():
    log(vm.comm('ls', '-1', '/'))
    log(vm.comm_out('ls', '-1', '/'))
    #vm.soft_reboot()
    #log(vm.comm('id'))
    log(vm.comm_out('oscap', 'info', '--profiles', '/usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml'))
    #log(vm.comm_out('dnf', 'install', '-y', 'aide'))
    #time.sleep(300)

#with vm.snapshotted():
#    vm.comm('mkdir', 'foob')
#    vm.copy_to('passwd', 'foob/dasswd')
#    out = vm.comm('cat', 'foob/dasswd')
#    log(out)

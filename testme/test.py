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

g = virt.Guest(virt.GUEST_NAME_GUI)

#g.install()
#g.prepare_for_snapshot()
if not g.can_be_snapshotted():
    g.install()
    g.prepare_for_snapshot()

with g.snapshotted():
    log(g.comm('ls', '-1', '/'))
    log(g.comm_out('ls', '-1', '/'))
    #g.soft_reboot()
    #log(g.comm('id'))
    log(g.comm_out('oscap', 'info', '--profiles', '/usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml'))
    #log(g.comm_out('dnf', 'install', '-y', 'aide'))
    #time.sleep(300)

#with g.snapshotted():
#    g.comm('mkdir', 'foob')
#    g.copy_to('passwd', 'foob/dasswd')
#    out = g.comm('cat', 'foob/dasswd')
#    log(out)

#!/usr/bin/python3

import os
import sys
import re
import time
import atexit
from logging import info as log

#sys.path.insert(0, '../lib')
import util
import results
import oscap


#util.setup_test_logging()
# TODO:
#atexit.register(tmt.pass_on_success)

log(f"hello from test! -- {__name__}")

#import requests
#x = requests.get('https://google.com')
#log(f"got req: {x}")


results.report('pass', 'some/result')

results.report('fail', 'another/result', logs=['/etc/passwd', '/etc/mtab'], note='foo \'"bar')

import virt

virt.setup_host()

#sys.exit(0)

g = virt.Guest('testme test')

#g.install()
#g.prepare_for_snapshot()
if not g.can_be_snapshotted():
    g.install()
    g.prepare_for_snapshot()

with g.snapshotted():
    log(g.ssh('ls', '-1', '/', capture=True))
    log(g.ssh('ls', '-1', '/'))
    #x = g.ssh_Popen('ls /etc', capture=True)
    #log(x.communicate())
    #g.soft_reboot()
    for line in g.ssh_stream(f'oscap info --profiles {oscap.datastream}'):
        log(f'GOT: --{line}--')
    #log(g.ssh('oscap', 'info', '--profiles', '/usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml'))
    #time.sleep(300)

results.report('pass')

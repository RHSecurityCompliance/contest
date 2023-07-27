#!/usr/bin/python3

from lib import util, results


res = util.subprocess_run(['oscap', 'info', '--fetch-remote-resources', util.get_datastream()])

status = 'pass' if res.returncode == 0 else 'fail'

results.report_and_exit(status)

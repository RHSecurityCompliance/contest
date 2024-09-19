#!/usr/bin/python3

from lib import util, results


profile = 'cis_workstation_l1'

extra_debuginfos = [
    'glibc',
    'openscap-scanner',
    'xmlsec1',
    'xmlsec1-openssl',
    'libtool-ltdl',
    'openssl-libs',
]

util.subprocess_run(['dnf', '-y', 'debuginfo-install', *extra_debuginfos], check=True)

oscap_cmd = [
    'valgrind', '--tool=helgrind', '--',
    'oscap', 'xccdf', 'eval', '--profile', profile, '--progress',
    util.get_datastream(),
]
util.subprocess_run(oscap_cmd)

results.report_and_exit()

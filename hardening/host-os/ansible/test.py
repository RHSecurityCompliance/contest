#!/usr/bin/python3

import os

from lib import util, results, oscap, ansible
from conf import remediation


profile = util.get_test_name().rpartition('/')[2]

# the VM guest ssh code doesn't use $HOME/.known_hosts, so Ansible blocks
# on trying to accept its ssh key - tell it to ignore this
os.environ['ANSIBLE_HOST_KEY_CHECKING'] = 'False'

if util.get_reboot_count() == 0:
    util.log("first boot, remediating using ansible-playbook")

    ansible.install_deps()

    pack = util.RpmPack()
    pack.install()

    playbook = util.get_playbook(profile)
    skip_tags = ','.join(remediation.excludes())
    skip_tags_arg = ['--skip-tags', skip_tags] if skip_tags else []
    cmd = [
        'ansible-playbook', '-v', '-c', 'local', '-i', 'localhost,',
        *skip_tags_arg,
        playbook,
    ]
    _, lines = util.subprocess_stream(cmd, check=True)
    ansible.report_from_output(lines)

    util.reboot()

else:
    util.log("second boot, scanning")

    # scan the remediated system
    cmd = [
        'oscap', 'xccdf', 'eval', '--profile', profile, '--progress',
        '--report', 'report.html', '--results-arf', 'scan-arf.xml',
        util.get_datastream(),
    ]
    proc, lines = util.subprocess_stream(cmd)
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    pack = util.RpmPack()
    pack.uninstall()

    util.subprocess_run(['gzip', '-9', 'scan-arf.xml'], check=True)

    results.report_and_exit(logs=['report.html', 'scan-arf.xml.gz'])

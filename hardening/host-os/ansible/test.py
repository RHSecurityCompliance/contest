#!/usr/bin/python3

import os
import subprocess

from lib import util, results, oscap, ansible
from conf import remediation


profile = util.get_test_name().rpartition('/')[2]

ansible_playbook_log = '/var/tmp/ansible-playbook.log'

# the VM guest ssh code doesn't use $HOME/.known_hosts, so Ansible blocks
# on trying to accept its ssh key - tell it to ignore this
os.environ['ANSIBLE_HOST_KEY_CHECKING'] = 'False'

if util.get_reboot_count() == 0:
    util.log("first boot, remediating using ansible-playbook")

    ansible.install_deps()

    pack = util.RpmPack()
    pack.add_sshd_late_start()
    pack.install()

    playbook = util.get_playbook(profile)
    skip_tags = ','.join(remediation.excludes())
    skip_tags_arg = ['--skip-tags', skip_tags] if skip_tags else []
    cmd = [
        'ansible-playbook', '-v', '-c', 'local', '-i', 'localhost,',
        *skip_tags_arg,
        playbook,
    ]
    proc, lines = util.subprocess_stream(cmd, stderr=subprocess.STDOUT)
    ansible.report_from_output(lines, to_file=ansible_playbook_log)
    results.add_log(ansible_playbook_log)
    if proc.returncode != 0:
        raise RuntimeError(f"ansible-playbook failed with {proc.returncode}")

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
        raise RuntimeError(f"post-reboot oscap failed unexpectedly with {proc.returncode}")

    pack = util.RpmPack()
    pack.uninstall()

    results.report_and_exit(logs=['report.html', 'scan-arf.xml'])

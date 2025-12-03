#!/usr/bin/python3

import os
import subprocess

from lib import util, results, ansible
from conf import remediation


profile = util.get_test_name().rpartition('/')[2]

# the VM guest ssh code doesn't use $HOME/.known_hosts, so Ansible blocks
# on trying to accept its ssh key - tell it to ignore this
os.environ['ANSIBLE_HOST_KEY_CHECKING'] = 'False'

ansible.install_deps()
playbook = util.get_playbook(profile)
skip_tags = ','.join(remediation.excludes())
skip_tags_arg = ['--skip-tags', skip_tags] if skip_tags else []
ansible_cmd = [
    'ansible-playbook', '-v', '-c', 'local', '-i', 'localhost,', '--check',
    *skip_tags_arg, playbook,
]
proc, lines = util.subprocess_stream(ansible_cmd, stderr=subprocess.STDOUT)
ansible.report_from_output(lines, to_file='ansible-playbook.log')
results.add_log('ansible-playbook.log')
if proc.returncode != 0:
    raise RuntimeError(f"ansible-playbook failed with {proc.returncode}")
results.report_and_exit()

#!/usr/bin/python3

import os
import subprocess

from lib import util, results, ansible


profile = util.get_test_name().rpartition('/')[2]

# the VM guest ssh code doesn't use $HOME/.known_hosts, so Ansible blocks
# on trying to accept its ssh key - tell it to ignore this
os.environ['ANSIBLE_HOST_KEY_CHECKING'] = 'False'

ansible.install_deps()
playbook = util.get_playbook(profile)
ansible_cmd = [
    'ansible-playbook', '-v', '-c', 'local', '-i', 'localhost,', '--check',
    playbook,
]
_, lines = util.subprocess_stream(ansible_cmd, stderr=subprocess.STDOUT, check=True)
ansible.report_from_output(lines, to_file='ansible-playbook.log')
util.subprocess_run(['gzip', '-9', 'ansible-playbook.log'], check=True)
results.report_and_exit(logs=['ansible-playbook.log.gz'])

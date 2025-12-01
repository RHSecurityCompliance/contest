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
proc, lines = util.subprocess_stream(ansible_cmd, stderr=subprocess.STDOUT)
ansible.report_from_output(lines, to_file='ansible-playbook.log')
util.subprocess_run(['gzip', '-9', 'ansible-playbook.log'], check=True, stderr=subprocess.PIPE)
results.add_log('ansible-playbook.log.gz')
if proc.returncode != 0:
    raise RuntimeError(f"ansible-playbook failed with {proc.returncode}")
results.report_and_exit()

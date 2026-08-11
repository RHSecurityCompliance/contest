#!/usr/bin/python3

import subprocess

from lib import ansible, util, results


def check_playbook(playbook, name):
    cmd = ['ansible-playbook', '--syntax-check', playbook]
    ret = util.subprocess_run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if ret.returncode == 0:
        results.report('pass', name)
    else:
        results.report('fail', name, ret.stdout)


ansible.install_deps()

ds = util.get_datastream()

# Check playbook from datastream and virtual (all) profile
cmd = [
    'oscap', 'xccdf', 'generate', 'fix', '--profile', '(all)',
    '--fix-type', 'ansible', '--output', 'playbook.yml', ds,
]
ret = util.subprocess_run(cmd, check=True, stderr=subprocess.PIPE)
check_playbook('playbook.yml', '(all) profile generated')

# Check shipped playbooks
for playbook in util.iter_playbooks():
    check_playbook(playbook, playbook.name)

# Check per-rule playbooks
for playbook in util.iter_per_rule_playbooks():
    check_playbook(playbook, playbook.name)

results.report_and_exit()

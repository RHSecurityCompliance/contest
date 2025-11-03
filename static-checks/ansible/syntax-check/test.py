#!/usr/bin/python3

import subprocess

from lib import ansible, util, results


ansible.install_deps()

ds = util.get_datastream()

# Generate playbook from datastream and virtual (all) profile
cmd = [
    'oscap', 'xccdf', 'generate', 'fix', '--profile', '(all)',
    '--fix-type', 'ansible', '--output', 'playbook.yml', ds,
]
ret = util.subprocess_run(cmd, check=True, stderr=subprocess.PIPE)

# Check syntax of generated playbook
cmd = ['ansible-playbook', '--syntax-check', 'playbook.yml']
ret = util.subprocess_run(cmd, stderr=subprocess.PIPE)
if ret.returncode == 0:
    results.report('pass', '(all) profile generated')
else:
    results.report('fail', '(all) profile generated', ret.stderr)

# Check syntax of shipped playbooks
for playbook in util.iter_playbooks():
    cmd = ['ansible-playbook', '--syntax-check', playbook]
    ret = util.subprocess_run(cmd, stderr=subprocess.PIPE)
    if ret.returncode == 0:
        results.report('pass', playbook.name)
    else:
        results.report('fail', playbook.name, ret.stderr)

results.report_and_exit()

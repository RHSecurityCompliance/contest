#!/usr/bin/python3

import subprocess

from lib import ansible, util, oscap, results


ansible.install_deps()

ds = util.get_datastream()
all_profiles = oscap.Datastream(ds).profiles

# Generated playbooks
for profile in all_profiles:
    # Get ARF from scan
    cmd = [
        'oscap', 'xccdf', 'eval', '--profile', profile,
        '--progress', '--results-arf', 'arf.xml', ds,
    ]
    ret = util.subprocess_run(cmd)
    if ret.returncode not in [0,2]:
        raise RuntimeError("oscap failed unexpectedly")

    # Generate playbook from results ARF
    cmd = [
        'oscap', 'xccdf', 'generate', 'fix', '--profile', profile,
        '--template', 'urn:xccdf:fix:script:ansible', '--output', 'playbook.yml', 'arf.xml',
    ]
    ret = util.subprocess_run(cmd, check=True)

    # Check syntax of generated playbook
    cmd = ['ansible-playbook', '--syntax-check', 'playbook.yml']
    ret = util.subprocess_run(cmd, stderr=subprocess.PIPE)
    if ret.returncode == 0:
        results.report('pass', f'{profile} scan generated')
    else:
        results.report('fail', f'{profile} scan generated', ret.stderr)

# Shipped playbooks
for playbook in util.iter_playbooks():
    cmd = ['ansible-playbook', '--syntax-check', playbook]
    ret = util.subprocess_run(cmd, stderr=subprocess.PIPE)
    if ret.returncode == 0:
        results.report('pass', playbook.name)
    else:
        results.report('fail', playbook.name, ret.stderr)

results.report_and_exit()

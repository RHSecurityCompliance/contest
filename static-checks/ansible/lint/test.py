#!/usr/bin/python3

import sys
import subprocess

from lib import ansible, util, results


def lint_playbook(playbook, name):
    cmd = [
        sys.executable, '-m', 'ansiblelint',
        '--offline', '--nocolor', '--profile', 'min',
        playbook,
    ]
    # ansible-lint writes violations to stdout
    ret = util.subprocess_run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if ret.returncode == 0:
        results.report('pass', name)
    else:
        results.report('fail', name, ret.stdout)


# Install via CONTEST_PYTHON (sys.executable), not bare pip3 - on RHEL-8/9
# pip3 targets the older system Python and cannot provide a modern ansible-lint.
if util.subprocess_run([sys.executable, '-m', 'pip', '--version']).returncode != 0:
    util.subprocess_run([sys.executable, '-m', 'ensurepip', '--upgrade'], check=True)

util.subprocess_run(
    [sys.executable, '-m', 'pip', 'install', 'ansible-lint'],
    check=True,
)

ansible.install_deps()

ds = util.get_datastream()

# lint generated playbook with virtual (all) profile
cmd = [
    'oscap', 'xccdf', 'generate', 'fix', '--profile', '(all)',
    '--fix-type', 'ansible', '--output', 'playbook.yml', ds,
]
util.subprocess_run(cmd, check=True, stderr=subprocess.PIPE)

lint_playbook('playbook.yml', '(all) profile generated')

# lint shipped playbooks
for playbook in util.iter_playbooks():
    lint_playbook(playbook, playbook.name)

# lint per-rule playbooks
for playbook in util.iter_per_rule_playbooks():
    lint_playbook(playbook, playbook.name)

results.report_and_exit()

#!/usr/bin/python3

import os
import subprocess

from lib import util, results, oscap, versions, ansible
from conf import remediation_excludes


profile = os.environ['PROFILE']
profile_full = f'xccdf_org.ssgproject.content_profile_{profile}'

# the VM guest ssh code doesn't use $HOME/.known_hosts, so Ansible blocks
# on trying to accept its ssh key - tell it to ignore this
os.environ['ANSIBLE_HOST_KEY_CHECKING'] = 'False'

if util.get_reboot_count() == 0:
    util.log("first boot, remediating using ansible-playbook")

    ansible.install_deps()

    playbook = util.get_playbook(profile)
    skip_tags = ','.join(remediation_excludes.ansible_skip_tags)
    skip_tags_arg = ['--skip-tags', skip_tags] if skip_tags else []
    cmd = [
        'ansible-playbook', '-v', '-c', 'local', '-i', 'localhost,',
        *skip_tags_arg,
        playbook,
    ]
    util.subprocess_run(cmd, check=True)

    # restore basic login functionality
    util.subprocess_run(['chage', '-d', '99999', 'root'], check=True)
    with open('/etc/sysconfig/sshd', 'a') as f:
        f.write('\nOPTIONS=-oPermitRootLogin=yes\n')

    util.reboot()

else:
    util.log("second boot, scanning")

    # old RHEL-7 oscap mixes errors into --progress rule names without a newline
    verbose = ['--verbose', 'INFO'] if versions.oscap >= 1.3 else []
    redir = {'stderr': subprocess.STDOUT} if versions.oscap >= 1.3 else {}
    # RHEL-7 HTML report doesn't contain OVAL findings by default
    oval_results = [] if versions.oscap >= 1.3 else ['--results', 'results.xml', '--oval-results']

    # scan the remediated system
    cmd = [
        'oscap', 'xccdf', 'eval', *verbose, '--profile', profile,
        '--progress', '--report', 'report.html', *oval_results,
        util.get_datastream(),
    ]
    proc, lines = util.subprocess_stream(cmd, **redir)
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    results.report_and_exit(logs=['report.html'])

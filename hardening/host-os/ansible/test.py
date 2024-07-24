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

    playbook = util.get_playbook(profile)
    skip_tags = ','.join(remediation.excludes())
    skip_tags_arg = ['--skip-tags', skip_tags] if skip_tags else []
    cmd = [
        'ansible-playbook', '-v', '-c', 'local', '-i', 'localhost,',
        *skip_tags_arg,
        playbook,
    ]
    proc, lines = util.subprocess_stream(cmd)
    failed = ansible.report_from_output(lines)
    if proc.returncode not in [0,2] or proc.returncode == 2 and not failed:
        raise RuntimeError(f"ansible-playbook failed with {proc.returncode}")

    # restore basic login functionality
    with open('/etc/sysconfig/sshd', 'a') as f:
        f.write('\nOPTIONS=-oPermitRootLogin=yes\n')

    util.reboot()

else:
    util.log("second boot, scanning")

    # scan the remediated system
    cmd = [
        'oscap', 'xccdf', 'eval', '--profile', profile, '--progress',
        '--report', 'report.html', '--results-arf', 'results-arf.xml',
        util.get_datastream(),
    ]
    proc, lines = util.subprocess_stream(cmd)
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    util.subprocess_run(['gzip', '-9', 'results-arf.xml'], check=True)

    results.report_and_exit(logs=['report.html', 'results-arf.xml.gz'])

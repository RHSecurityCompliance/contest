#!/usr/bin/python3

import os

from lib import util, results, virt, oscap, versions, ansible
from conf.remediation_excludes import rule_excludes


ansible.install_deps()
virt.setup_host()

profile = os.environ['PROFILE']
profile_full = f'xccdf_org.ssgproject.content_profile_{profile}'

use_gui = os.environ.get('USE_SERVER_WITH_GUI')

if use_gui:
    g = virt.Guest('gui_with_oscap')
else:
    g = virt.Guest('minimal_with_oscap')

if not g.can_be_snapshotted():
    ks = virt.Kickstart()
    if use_gui:
        ks.add_package_group('Server with GUI')
    g.install(kickstart=ks)
    g.prepare_for_snapshot()

# the VM guest ssh code doesn't use $HOME/.known_hosts, so Ansible blocks
# on trying to accept its ssh key - tell it to ignore this
os.environ['ANSIBLE_HOST_KEY_CHECKING'] = 'False'

with g.snapshotted():
    # remediate using a locally-run 'ansible-playbook', which connects
    # to the guest using ssh
    playbook = util.get_playbook(profile)
    skip_tags = ','.join(rule_excludes)
    skip_tags_arg = ['--skip-tags', skip_tags] if skip_tags else []
    ansible_cmd = [
        'ansible-playbook', '-v', '-i', f'{g.ipaddr},',
        '--private-key', g.ssh_keyfile_path,
        *skip_tags_arg,
        playbook,
    ]
    util.subprocess_run(ansible_cmd, check=True)
    g.soft_reboot()

    # old RHEL-7 oscap mixes errors into --progress rule names without a newline
    verbose = '--verbose INFO' if versions.oscap >= 1.3 else ''
    redir = '2>&1' if versions.oscap >= 1.3 else ''
    # RHEL-7 HTML report doesn't contain OVAL findings by default
    oval_results = '' if versions.oscap >= 1.3 else '--results results.xml --oval-results'

    # scan the remediated system
    g.copy_to(util.get_datastream(), 'contest-ds.xml')
    proc, lines = g.ssh_stream(f'oscap xccdf eval {verbose} --profile {profile_full} --progress '
                               f'--report report.html {oval_results} contest-ds.xml {redir}')
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')

results.report_and_exit(logs=['report.html'])

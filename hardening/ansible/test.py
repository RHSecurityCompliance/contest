#!/usr/bin/python3

import os
import subprocess

from lib import util, results, virt, oscap, ansible, metadata
from conf import remediation, partitions


ansible.install_deps()
virt.Host.setup()

profile = util.get_test_name().rpartition('/')[2]

guest_tag = virt.calculate_guest_tag(metadata.tags())
g = virt.Guest(guest_tag)

if not g.can_be_snapshotted():
    ks = virt.Kickstart(partitions=partitions.partitions)
    if 'with-gui' in metadata.tags():
        ks.packages.append('@Server with GUI')
    g.install(
        kickstart=ks,
        secure_boot=('uefi' in metadata.tags()),
        kernel_args=['fips=1'] if 'fips' in metadata.tags() else None,
    )
    g.prepare_for_snapshot()

# the VM guest ssh code doesn't use $HOME/.known_hosts, so Ansible blocks
# on trying to accept its ssh key - tell it to ignore this
os.environ['ANSIBLE_HOST_KEY_CHECKING'] = 'False'

with g.snapshotted():
    # remediate using a locally-run 'ansible-playbook', which connects
    # to the guest using ssh
    playbook = util.get_playbook(profile)
    skip_tags = ','.join(remediation.excludes())
    skip_tags_arg = ['--skip-tags', skip_tags] if skip_tags else []
    ansible_cmd = [
        'ansible-playbook', '-v', '-i', f'{g.ipaddr},',
        '--private-key', g.ssh_keyfile_path,
        *skip_tags_arg,
        playbook,
    ]
    _, lines = util.subprocess_stream(ansible_cmd, stderr=subprocess.STDOUT, check=True)
    ansible.report_from_output(lines, to_file='ansible-playbook.log')
    g.soft_reboot()

    # scan the remediated system
    g.copy_to(util.get_datastream(), 'scan-ds.xml')
    proc, lines = g.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf scan-arf.xml scan-ds.xml',
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError(f"post-reboot oscap failed unexpectedly with {proc.returncode}")

    g.copy_from('report.html')
    g.copy_from('scan-arf.xml')

util.subprocess_run(['gzip', '-9', 'scan-arf.xml'], check=True)
util.subprocess_run(['gzip', '-9', 'ansible-playbook.log'], check=True)

results.report_and_exit(logs=['report.html', 'scan-arf.xml.gz', 'ansible-playbook.log.gz'])

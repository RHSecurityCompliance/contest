#!/usr/bin/python3

import os

from lib import util, results, virt, oscap, ansible
from conf import remediation, partitions


ansible.install_deps()
virt.Host.setup()

_, variant, profile = util.get_test_name().rsplit('/', 2)

if variant == 'with-gui':
    g = virt.Guest('gui_with_oscap')
elif variant == 'uefi':
    g = virt.Guest('uefi_with_oscap')
else:
    g = virt.Guest('minimal_with_oscap')

if not g.can_be_snapshotted():
    ks = virt.Kickstart(partitions=partitions.partitions)
    if variant == 'with-gui':
        ks.packages.append('@Server with GUI')
    g.install(kickstart=ks, secure_boot=(variant == 'uefi'))
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
    proc, lines = util.subprocess_stream(ansible_cmd)
    failed = ansible.report_from_output(lines)
    if proc.returncode not in [0,2] or proc.returncode == 2 and not failed:
        raise RuntimeError(f"ansible-playbook failed with {proc.returncode}")
    g.soft_reboot()

    # scan the remediated system
    g.copy_to(util.get_datastream(), 'scan-ds.xml')
    proc, lines = g.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf results-arf.xml scan-ds.xml'
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    g.copy_from('report.html')
    g.copy_from('results-arf.xml')

util.subprocess_run(['gzip', '-9', 'results-arf.xml'], check=True)

results.report_and_exit(logs=['report.html', 'results-arf.xml.gz'])

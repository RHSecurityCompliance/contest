#!/usr/bin/python3

import os
import atexit
import subprocess

import shared
from lib import util, results, virt, versions, ansible, metadata
from conf import partitions, remediation


ansible.install_deps()
virt.Host.setup()

guest_tag = virt.calculate_guest_tag(metadata.tags())
g = virt.Guest(guest_tag)

if not g.is_installed():
    ks = virt.Kickstart(partitions=partitions.partitions)
    g.install(kickstart=ks, kernel_args=['fips=1'])

g.prepare_for_snapshot()
atexit.register(g.cleanup_snapshot)

# the VM guest ssh code doesn't use $HOME/.known_hosts, so Ansible blocks
# on trying to accept its ssh key - tell it to ignore this
os.environ['ANSIBLE_HOST_KEY_CHECKING'] = 'False'

with g.snapshotted():
    playbook = util.get_playbook(shared.profile)
    skip_tags = ','.join(remediation.excludes())
    skip_tags_arg = ['--skip-tags', skip_tags] if skip_tags else []
    ansible_cmd = [
        'ansible-playbook', '-v', '-i', f'{g.ipaddr},',
        '--private-key', g.ssh_keyfile_path,
        *skip_tags_arg,
        playbook,
    ]
    proc, lines = util.subprocess_stream(ansible_cmd, stderr=subprocess.STDOUT)
    ansible.report_from_output(lines, to_file='ansible-playbook.log')
    util.subprocess_run(['gzip', '-9', 'ansible-playbook.log'], check=True, stderr=subprocess.PIPE)
    results.add_log('ansible-playbook.log.gz')
    if proc.returncode != 0:
        raise RuntimeError(f"ansible-playbook failed with {proc.returncode}")
    g.soft_reboot()

    with util.get_source_content() as content_dir:
        g.copy_to(util.get_datastream(), 'ssg-ds.xml')
        shared.content_scan(g, 'ssg-ds.xml', html='ssg-report.html', arf='ssg-arf.xml')
        g.copy_from('ssg-report.html')
        g.copy_from('ssg-arf.xml')

        # There is always one (the latest) DISA benchmark in content src
        references = content_dir / 'shared' / 'references'
        disa_ds = next(
            references.glob(f'disa-stig-rhel{versions.rhel.major}-*-xccdf-scap.xml'),
        )
        g.copy_to(disa_ds, 'disa-ds.xml')
        shared.disa_scan(g, 'disa-ds.xml', html='disa-report.html', arf='disa-arf.xml')
        g.copy_from('disa-report.html')
        g.copy_from('disa-arf.xml')

        # Compare ARFs and report results from output
        shared.compare_arfs('ssg-arf.xml', 'disa-arf.xml')

results.report_and_exit(logs=['ssg-report.html', 'disa-report.html'])

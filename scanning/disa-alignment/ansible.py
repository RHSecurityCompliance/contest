#!/usr/bin/python3
import os

import shared
from lib import util, results, virt, versions, ansible
from conf import partitions, remediation


ansible.install_deps()
virt.Host.setup()

g = virt.Guest('minimal_with_oscap')

if not g.can_be_snapshotted():
    ks = virt.Kickstart(partitions=partitions.partitions)
    g.install(kickstart=ks)
    g.prepare_for_snapshot()

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
    _, lines = util.subprocess_stream(ansible_cmd, check=True)
    ansible.report_from_output(lines)
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

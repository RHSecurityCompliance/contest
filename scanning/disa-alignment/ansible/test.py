#!/usr/bin/python3
import os
import re
import subprocess

from lib import util, results, virt, versions, ansible
from conf import partitions, remediation


ansible.install_deps()
virt.Host.setup()

profile = 'xccdf_org.ssgproject.content_profile_stig'

g = virt.Guest('minimal_with_oscap')

if not g.can_be_snapshotted():
    ks = virt.Kickstart(partitions=partitions.partitions)
    g.install(kickstart=ks)
    g.prepare_for_snapshot()

# the VM guest ssh code doesn't use $HOME/.known_hosts, so Ansible blocks
# on trying to accept its ssh key - tell it to ignore this
os.environ['ANSIBLE_HOST_KEY_CHECKING'] = 'False'

with g.snapshotted():
    playbook = util.get_playbook('stig')
    skip_tags = ','.join(remediation.excludes())
    skip_tags_arg = ['--skip-tags', skip_tags] if skip_tags else []
    ansible_cmd = [
        'ansible-playbook', '-v', '-i', f'{g.ipaddr},',
        '--private-key', g.ssh_keyfile_path,
        *skip_tags_arg,
        playbook,
    ]
    util.subprocess_run(ansible_cmd, check=True)
    g.soft_reboot()

    with util.get_content() as content_dir:
        # There is always one (the latest) DISA benchmark in content src
        references = content_dir / 'shared' / 'references'
        disa_ds = next(
            references.glob(f'disa-stig-rhel{versions.rhel.major}-*-xccdf-scap.xml')
        )

        # old RHEL-7 oscap mixes errors into --progress rule names without a newline
        redir = '2>&1' if versions.oscap >= 1.3 else ''
        # RHEL-7 HTML report doesn't contain OVAL findings by default
        oval_results = '' if versions.oscap >= 1.3 else '--results results.xml --oval-results'

        shared_cmd = ['oscap', 'xccdf', 'eval', '--progress', oval_results]
        # Scan with scap-security-guide benchmark
        g.copy_to(util.get_datastream(), 'ssg-ds.xml')
        cmd = [
            *shared_cmd,
            '--profile', profile,
            '--report', 'ssg-report.html',
            '--stig-viewer', 'ssg-stig-viewer.xml',
            'ssg-ds.xml', redir,
        ]
        proc = g.ssh(' '. join(cmd))
        if proc.returncode not in [0,2]:
            raise RuntimeError(f"remediation oscap failed with {proc.returncode}")
        g.copy_from('ssg-report.html')
        g.copy_from('ssg-stig-viewer.xml')

        # Scan with DISA benchmark
        g.copy_to(disa_ds, 'disa-ds.xml')
        cmd = [
            *shared_cmd,
            '--profile', '\'(all)\'',
            '--report', 'disa-report.html',
            '--results-arf', 'disa-arf.xml',
            'disa-ds.xml', redir
        ]
        proc = g.ssh(' '. join(cmd))
        if proc.returncode not in [0,2]:
            raise RuntimeError(f"remediation oscap failed with {proc.returncode}")
        g.copy_from('disa-report.html')
        g.copy_from('disa-arf.xml')

        compare_script = content_dir / 'utils' / 'compare_results.py'
        env = os.environ.copy()
        env['PYTHONPATH'] = str(content_dir)
        cmd = [
            compare_script, 'ssg-stig-viewer.xml', 'disa-arf.xml',
        ]
        proc = util.subprocess_run(cmd, env=env, universal_newlines=True, stdout=subprocess.PIPE)

        # Same result format:      CCE CCI - DISA_RULE_ID SSG_RULE_ID     RESULT
        # Different result format: CCE CCI - DISA_RULE_ID SSG_RULE_ID     SSG_RESULT - DISA_RESULT
        result_regex = re.compile(r'[\w-]+ [\w-]+ - [\w-]+ (\w*)\s+(\w+)(?: - *(\w+))*')
        for match in result_regex.finditer(proc.stdout.rstrip('\n')):
            rule_id, ssg_result, disa_result = match.groups()
            if not rule_id:
                rule_id = 'rule_id_not_found'
            # Only 1 result matched - same results
            if not disa_result:
                results.report('pass', rule_id)
            # SSG CPE checks can make rule notapplicable by different reason (package not
            # installed, architecture, RHEL version). DISA bechmark doesn't have this
            # capability, it just 'pass'. Ignore such result misalignments
            elif ssg_result == 'notapplicable' and disa_result == 'pass':
                result_note = 'SSG result: notapplicable, DISA result: pass'
                results.report('pass', rule_id, result_note)
            # Different results
            else:
                result_note = f'SSG result: {ssg_result}, DISA result: {disa_result}'
                results.report('fail', rule_id, result_note)

results.report_and_exit(logs=['ssg-report.html', 'disa-report.html'])

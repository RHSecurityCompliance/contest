#!/usr/bin/python3

import os
import sys
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

from lib import util, results, oscap, virt, versions, ansible
from conf import partitions


def between_strings(full_text, before, after):
    """
    Cut off a middle section of a 'full_text' string between the
    'before' and 'after' substrings.
    """
    start = full_text.find(before)
    if start == -1:
        start = 0
    end = full_text[start+len(before):].find(after)
    if end == -1:
        return full_text[start:]
    else:
        return full_text[start:start+len(before)+end]


def report_test_with_log(status, note, log_dir, rule_name, test_name):
    # collect additional automatus.py-generated files and reports
    extras_all = []
    extras_logs = []
    extras_prefix = f'{rule_name}-{test_name}.sh-'

    for path in log_dir.glob(f'{extras_prefix}*'):
        # rename automatus.py generated files to simple names,
        # rule_name-test_name.sh-initial.html -> initial.html
        # TODO: python 3.9+
        #basename = path.name.removeprefix(extras_prefix)
        basename = re.sub(fr'^{extras_prefix}', '', path.name, count=1)
        path.rename(path.parent / basename)
        path = path.parent / basename

        if basename == 'initial.html':
            extras_logs.append(path)
        elif basename == 'initial-arf.xml':
            util.subprocess_run(['gzip', '-9', path], check=True)
            path = path.with_suffix('.xml.gz')
            extras_logs.append(path)

        extras_all.append(path)

    # handle test script outputs:
    # Automatus groups test outputs by rule (one file per rule),
    # and it uses ##### denoted sections for individual tests outputs
    # within each file
    log_file = log_dir / (rule_name + '.prescripts.log')
    log = log_file.read_text()
    log_part = between_strings(
        log,
        f'##### {rule_name} / {test_name}',
        f'##### {rule_name} / ',
    )

    # report the result
    with tempfile.TemporaryDirectory() as tmpdir:
        log_part_file = Path(tmpdir) / 'out.txt'
        log_part_file.write_text(log_part)
        results.report(
            status,
            f'{rule_name}/{test_name}',
            note,
            logs=[log_part_file, *extras_logs],
        )

    # clean up logs for this test
    for path in extras_all:
        path.unlink()


virt.Host.setup()

# /per-rule/from-env/oscap --> test_basename=from-env, fix_type=oscap
test_basename, fix_type = util.get_test_name().rsplit('/')[-2:]
if test_basename == 'from-env':
    our_rules = os.environ.get('RULE')
    if our_rules:
        our_rules = our_rules.split()  # space-separated
    else:
        raise RuntimeError("RULE env variable not defined or empty")
else:
    all_rules = sorted(oscap.global_ds().get_all_profiles_rules())
    start = int(test_basename) - 1
    total = int(os.environ['TOTAL_SLICES'])
    # slice all_rules, get every total-th member
    our_rules = all_rules[start::total]

if not our_rules:
    raise RuntimeError("no rules to test")

if fix_type == 'ansible':
    ansible.install_deps()

our_rules_textblock = textwrap.indent(('\n'.join(our_rules)), '    ')
util.log(f"testing rules:\n{our_rules_textblock}")

# tag named after the tool that modifies the VM/image
g = virt.Guest('automatus')

if not g.is_installed():
    # install a qcow2-backed VM, so automatus.py can snapshot it
    # - use hardening-style partitions, automatus tests need them
    ks = virt.Kickstart(partitions=partitions.partitions)
    ks.packages.append('tar')
    g.install(kickstart=ks, disk_format='qcow2')

with util.get_source_content() as content_dir, g.booted():
    util.build_content(content_dir, force=True)
    env = os.environ.copy()
    env['SSH_ADDITIONAL_OPTIONS'] = f'-o IdentityFile={g.ssh_keyfile_path}'
    cmd = [
        './automatus.py', 'rule',
        '--libvirt', 'qemu:///system', virt.GUEST_NAME,
        '--product', f'rhel{versions.rhel.major}',
        '--dontclean', '--remediate-using', fix_type,
        '--datastream', util.get_datastream(),
        *our_rules,
    ]
    _, lines = util.subprocess_stream(
        cmd, check=True, stderr=subprocess.STDOUT,
        env=env, cwd=(content_dir / 'tests'),
    )

    log_file = rule_name = None
    for line in lines:
        # copy the exact output to console
        sys.stdout.write(f'{line}\n')
        sys.stdout.flush()

        # cut off log level
        line = re.sub(r'^[A-Z]+ - ', '', line, count=1, flags=re.M)

        # rule without remediation
        match = re.fullmatch(r'''No remediation is available for rule 'xccdf_org\.ssgproject\.content_rule_(.+)'\.''', line)  # noqa
        if match:
            rule_name = match.group(1)
            results.report('info', rule_name, 'no remediation')
            continue

        # remember the log file for log parsing/upload
        #   INFO - Logging into /tmp/.../logs/rule-custom-2024-02-17-1859/test_suite.log
        match = re.fullmatch(r'Logging into (.+)', line)
        if match:
            log_dir = Path(match.group(1)).parent
            util.log(f"using automatus log dir: {log_dir}")
            continue

        # running tests for a new rule
        #   INFO - xccdf_org.ssgproject.content_rule_timer_dnf-automatic_enabled
        match = re.fullmatch(r'xccdf_org\.ssgproject\.content_rule_(.+)', line)
        if match:
            rule_name = match.group(1)
            util.log(f"running for rule: {rule_name}")
            continue

        # result for one test - report it under the current rule:
        #   INFO - Script line_missing.fail.sh using profile (all) OK
        #   WARNING - Script correct_option.pass.sh using profile (all) notapplicable
        #   ERROR - Script correct.pass.sh using profile (all) found issue:
        match = re.fullmatch(r'Script (.+).sh using profile ([^ ]+) (.+)', line)
        if match:
            test_name, profile, status = match.groups()
            # TODO: python 3.9+
            #profile = profile.removeprefix('xccdf_org.ssgproject.content_profile_')
            profile = re.sub(r'^xccdf_org.ssgproject.content_profile_', '', profile, count=1)

            if status == 'OK':
                status = 'pass'
                note = f'profile:{profile}' if profile != '(all)' else None
            elif status == 'notapplicable':
                status = 'info'
                note = 'not applicable'
            elif status == 'found issue:':
                status = 'fail'
                note = f'profile:{profile}' if profile != '(all)' else None
            else:
                status = 'error'
                note = "unknown Script status"

            report_test_with_log(status, note, log_dir, rule_name, test_name)
            continue

        # this is separate, because Automatus prints 4 ERROR lines for this,
        # using a non-standard format (unlike the above):
        #   ERROR - Rule evaluation resulted in error, instead of expected fixed during remediation stage        # noqa
        #   ERROR - The remediation failed for rule 'xccdf_org.ssgproject.content_rule_tftpd_uses_secure_mode'.  # noqa
        #   ERROR - Rule 'tftpd_uses_secure_mode' test setup script 'wrong.fail.sh' failed with exit code 1      # noqa
        #   ERROR - Environment failed to prepare, skipping test
        # so we parse just the one important line and ignore the rest
        match = re.fullmatch(r'''Rule '[^']+' test setup script '(.+).sh' failed with exit code [0-9]+''', line)  # noqa
        if match:
            test_name = match.group(1)
            report_test_with_log('fail', None, log_dir, rule_name, test_name)
            continue

results.report_and_exit()

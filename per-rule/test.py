#!/usr/bin/python3

import os
import sys
import re
import subprocess
import contextlib
import tempfile
import textwrap
import distutils.dir_util
from pathlib import Path

from lib import util, results, oscap, virt, versions, dnf
from conf import partitions


@contextlib.contextmanager
def get_content():
    from_env = os.environ.get('CONTENT_SOURCE')
    if from_env:
        content = Path(from_env)
        build_dir = content / 'build'

        # if it has built content
        if (build_dir / 'Makefile').exists():
            util.log(f"using pre-built content: {build_dir}")
            yield content

        # manually build the source
        else:
            util.log(f"building content from source: {content}")
            with tempfile.TemporaryDirectory() as tmpdir:
                # TODO: this should be shutil.copytree(.., dirs_exist_ok=True) on python 3.8+
                distutils.dir_util.copy_tree(content, tmpdir)
                util.log(f"using {tmpdir} as content source")
                # install dependencies
                cmd = ['dnf', '-y', 'builddep', '--spec', 'scap-security-guide.spec']
                util.subprocess_run(cmd, check=True, cwd=tmpdir)
                # build content
                cmd = ['./build_product', f'rhel{versions.rhel.major}']
                util.subprocess_run(cmd, check=True, cwd=tmpdir)
                yield Path(tmpdir)

    else:
        # fall back to SRPM
        with dnf.download_rpm('scap-security-guide', source=True) as src_rpm:
            with tempfile.TemporaryDirectory() as tmpdir:
                # install dependencies
                cmd = ['dnf', '-y', 'builddep', '--srpm', src_rpm]
                util.subprocess_run(cmd, check=True, cwd=tmpdir)
                # extract + patch SRPM
                cmd = ['rpmbuild', '-rp', '--define', f'_topdir {tmpdir}', src_rpm]
                util.subprocess_run(cmd, check=True)
                # get path to the extracted content
                # - parse name+version from the SRPM instead of glob(BUILD/*)
                #   because of '-rhel6' content on RHEL-8
                ret = util.subprocess_run(
                    ['rpm', '-q', '--qf', '%{NAME}-%{VERSION}', '-p', src_rpm],
                    check=True, stdout=subprocess.PIPE, universal_newlines=True, cwd=tmpdir,
                )
                name_version = ret.stdout.strip()
                extracted = Path(tmpdir) / 'BUILD' / name_version
                util.log(f"using {extracted} as content source")
                if not extracted.exists():
                    raise FileNotFoundError(f"{extracted} not in extracted/patched SRPM")
                # build content
                # TODO: temporary, see https://github.com/ComplianceAsCode/content/pull/11606
                (extracted / 'build').mkdir(exist_ok=True)
                cmd = ['./build_product', f'rhel{versions.rhel.major}']
                util.subprocess_run(cmd, check=True, cwd=extracted)
                yield extracted


def slice_list(full_list, divident, divisor):
    """
    Slice a 'full_list' into approx. equally-sized 'divisor' parts,
    return the 'divident' slice.
    """
    total = len(full_list)
    quotient = int(total / divisor)
    remainder = total % divisor
    # add 1 to the first dividents, up until all the added 1s
    # are consumed (they add up to a value equal to remainder)
    count = quotient + (1 if remainder >= divident else 0)
    # starting index, from 0, with remainder gradually added,
    # capped by max remainder value
    start = (divident-1)*quotient + min(remainder, (divident-1))
    # end = start of current slice + amount
    # (as last valid index + 1, for python slice end)
    end = start + count
    # return a slice of the original list rather than copying it
    return full_list[start:end]


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
    # Automatus groups test outputs by rule (one file per rule),
    # and it uses ##### denoted sections for individual tests outputs
    # within each file
    log_file = log_dir / (rule_name + '.prescripts.log')
    log = log_file.read_text()
    log_part = between_strings(
        log,
        f'##### {rule_name} / {test_name}',
        f'##### {rule_name} / '
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        log_part_file = Path(tmpdir) / 'out.txt'
        log_part_file.write_text(log_part)
        results.report(status, f'{rule_name}/{test_name}', note, logs=[log_part_file])


virt.Host.setup()

with get_content() as content_dir:
    test_basename = util.get_test_name().rsplit('/', 1)[1]
    if test_basename == 'from-env':
        our_rules = os.environ.get('RULE')
        if our_rules:
            our_rules = our_rules.split()  # space-separated
        else:
            raise RuntimeError("RULE env variable not defined or empty")
    else:
        our_rules = slice_list(
            oscap.get_all_profiles_rules(),
            int(os.environ['SLICE']),
            int(os.environ['TOTAL_SLICES'])
        )

    our_rules_textblock = textwrap.indent(('\n'.join(our_rules)), '    ')
    util.log(f"testing rules:\n{our_rules_textblock}")

    g = virt.Guest()

    # install a qcow2-backed VM, so automatus.py can snapshot it
    # - use hardening-style partitions, automatus tests need them
    ks = virt.Kickstart(partitions=partitions.partitions)
    g.install(kickstart=ks, disk_format='qcow2')

    with g.booted():
        env = os.environ.copy()
        env['SSH_ADDITIONAL_OPTIONS'] = f'-o IdentityFile={g.ssh_keyfile_path}'
        cmd = [
            './automatus.py', 'rule',
            '--libvirt', 'qemu:///system', virt.GUEST_NAME,
            '--product', f'rhel{versions.rhel.major}',
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
            line = re.sub('^[A-Z]+ - ', '', line, count=1, flags=re.M)

            # rule without remediation
            match = re.fullmatch(r'''No remediation is available for rule 'xccdf_org\.ssgproject\.content_rule_(.+)'\.''', line)  # noqa
            if match:
                rule_name = match.group(1)
                results.report('info', rule_name, 'no remediation')
                continue

            # remember the log file for log parsing/upload
            #   INFO - Logging into /tmp/.../logs/rule-custom-2024-02-17-1859/test_suite.log
            match = re.fullmatch('Logging into (.+)', line)
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
                profile = re.sub('^xccdf_org.ssgproject.content_profile_', '', profile, count=1)

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

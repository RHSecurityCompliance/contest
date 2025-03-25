#!/usr/bin/python3

import os
import re
import inspect
import subprocess
from pathlib import Path

from lib import util, results, versions, virt, oscap, unit_tests
from conf import remediation

rule_excludes = [
    # because of inter-rule dependencies and their incompatibility with
    # thin datastreams:
    #   W: oscap: Rule 'xccdf_org.ssgproject.content_rule_sshd_set_keepalive'
    #   requires rule 'xccdf_org.ssgproject.content_rule_sshd_set_idle_timeout',
    #   but it hasn't been specified using the '--rule' option.
    'sshd_set_keepalive',
]

_, fix_type, test_basename = util.get_test_name().rsplit('/', 2)

# directory containing this test.py; necessary because we run in a tmpdir
testdir = Path(inspect.getfile(inspect.currentframe())).parent

virt.Host.setup()

remediation_excludes = set(remediation.excludes())


def format_test(test):
    pass_fail = 'pass' if test.is_pass else 'fail'
    return f'{test.rule}/{test.test}.{pass_fail}'


def unit_tests_from_rules(built_tests_dir, rules):
    for rule in sorted(rules):
        rule_dir = built_tests_dir / rule
        # rule without tests
        if not rule_dir.is_dir():
            continue
        for partial, test_file in unit_tests.iter_tests(rule_dir):
            try:
                full = unit_tests.fill_in_metadata(partial, test_file)
            except ValueError as e:
                results.report(
                    'error',
                    format_test(partial),
                    f"metadata syntax error: {str(e)}",
                )
                continue
            # skip explicitly excluded rules
            if full.rule in rule_excludes:
                continue
            # skip any tests with profile= for now
            if full.profiles:
                continue
            # skip .fail.sh tests that require remediation for rules that we
            # explicitly avoid remediation for
            if not full.is_pass and full.remediation != 'none':
                if full.rule in remediation_excludes:
                    continue
            yield full


with util.get_source_content() as content_dir:
    # thin datastreams cannot be built alongside other content, build them first
    # (separately), move aside the XMLs
    util.build_content(
        content_dir,
        {
            'SSG_THIN_DS:BOOL': 'ON',
            'SSG_THIN_DS_RULE_ID:STRING': 'ALL_RULES',
            'SSG_BUILT_TESTS_ENABLED:BOOL': 'ON',
            'SSG_ANSIBLE_PLAYBOOKS_PER_RULE_ENABLED:BOOL': 'ON',
        },
    )
    build_dir = content_dir / util.CONTENT_BUILD_DIR
    product_dir = build_dir / f'rhel{versions.rhel.major}'
    thin_ds_dir = build_dir / 'thin_ds'

    ds_path = util.get_datastream(content_dir=content_dir)
    ds = oscap.Datastream(ds_path)
    built_tests = product_dir / 'tests'
    playbooks_dir = util.find_per_rule_playbooks(content_dir=content_dir)

    if test_basename == 'from-env':
        our_rules = os.environ.get('RULE')
        if not our_rules:
            raise RuntimeError("RULE env variable not defined or empty")
        our_rules = re.split(r'[, ]+', our_rules)
    else:
        if 'RULE' in os.environ:
            raise RuntimeError("RULE env variable defined, but not running as from-env")
        all_rules = sorted(ds.get_all_profiles_rules())
        start = int(test_basename) - 1
        total = int(os.environ['TOTAL_SLICES'])
        # slice all_rules, get every total-th member
        our_rules = all_rules[start::total]

    util.log(f"will be testing {len(our_rules)} rules")

    tests = unit_tests_from_rules(built_tests, our_rules)
    # if remediating via ansible, filter out any tests without playbooks
    if fix_type == 'ansible':
        tests = (t for t in tests if (playbooks_dir / f'{t.rule}.yml').exists())
    tests = list(tests)
    if not tests:
        raise RuntimeError("no tests to run")

    # write out all variables for all tests
    # (we do this instead of passing them as CLI arguments because variable
    #  values may contain spaces, special chars like $, backslash, etc.,
    #  and ssh(1) always works with shell input, not discrete CLI args)
    vars_dir = Path('variables')
    vars_dir.mkdir()
    for test in tests:
        if not test.variables:
            continue
        vars_rule_dir = vars_dir / test.rule
        vars_rule_dir.mkdir(exist_ok=True)
        filename = f'{test.test}.' + ('pass' if test.is_pass else 'fail')
        with open(vars_rule_dir / filename, 'w') as f:
            for key, value in test.variables.items():
                f.write(f'{key}={value}\n')

    # collect all packages from all unit_tests
    packages = {pkg for t in tests if t.packages is not None for pkg in t.packages}

    # prepare a kickstart for the VM
    ks = virt.Kickstart()
    ks.packages += ['rsync', 'xmlstarlet', 'ansible-core']
    # if RHEL, use rhc-worker-playbook, else install from galaxy
    if versions.rhel.is_true_rhel():
        ks.packages.append('rhc-worker-playbook')
        # per https://access.redhat.com/articles/remediation
        ks.add_post(util.dedent('''
            cat >> /etc/ansible/ansible.cfg <<EOF
            [defaults]
            collections_path=/usr/share/rhc-worker-playbook/ansible/collections/ansible_collections/
            EOF
        '''))
    else:
        ks.add_post(util.dedent('''
            ansible-galaxy collection install community.general
            ansible-galaxy collection install ansible.posix
        '''))

    # install the VM
    g = virt.Guest()
    g.install(kickstart=ks, final_mem=None)

    with g.booted(safe_shutdown=True):
        # install extra test dependencies now
        # (Anaconda seems to crash with some of these, hence install-after-boot)
        if packages:
            g.ssh('dnf install -y --skip-broken', *packages, check=True)
        # copy built artifacts to the guest
        g.rsync_to(f'{thin_ds_dir}/', 'thin_ds')
        g.rsync_to(f'{built_tests}/', 'tests')
        g.rsync_to(f'{vars_dir}/', 'variables')
        g.rsync_to(f'{playbooks_dir}/', 'playbooks')
        # copy guest setup/runner
        g.rsync_to((testdir / 'setup.sh', testdir / 'runner.sh'))
        g.ssh('chmod 0755 setup.sh runner.sh', check=True)
        # perform additional guest setup
        # - this modifies some testing data, which is why we do it in the guest,
        #   rather than from python here - we want to preserve content_dir as-is
        g.ssh('./setup.sh', check=True)

    g.prepare_for_snapshot()

guest_logs_template = [
    'initial-report.html', 'initial-results-arf.xml',
    'report.html', 'results-arf.xml',
    'ds.xml', *(('playbook.yml',) if fix_type == 'ansible' else ()),
    'runner.log', 'test.log',
]

for test in tests:
    pass_fail = 'pass' if test.is_pass else 'fail'
    guest_logs = [*guest_logs_template, f'test.{pass_fail}.sh']

    # skip tests with explicitly defined remediation that is != the fix_type
    # we started with (according to fmf metadata)
    if test.remediation == 'bash' and fix_type != 'oscap':
        continue
    if test.remediation == 'ansible' and fix_type != 'ansible':
        continue

    # if unspecified by test, default to test type from fmf metadata
    if test.remediation == 'bash':
        remediation_type = 'oscap'
    elif test.remediation:
        remediation_type = test.remediation
    else:
        remediation_type = fix_type

    # try a first run, if it passes, report it without extra overhead
    with g.snapshotted():
        proc = g.ssh(
            './runner.sh', test.rule, test.test, pass_fail, remediation_type, 'nodebug',
            stdout=subprocess.PIPE, universal_newlines=True,
        )
        if proc.returncode == 0:
            results.report('pass', format_test(test), proc.stdout.rstrip('\n'))
            continue
        elif proc.returncode == 3:
            results.report('skip', format_test(test), proc.stdout.rstrip('\n'))
            continue

    # something failed, do a second run and collect debug details
    # - note that it is possible the fail was transient and the following
    #   may still pass
    with g.snapshotted():
        proc = g.ssh(
            './runner.sh', test.rule, test.test, pass_fail, remediation_type, 'debug',
            stdout=subprocess.PIPE, universal_newlines=True,
        )

        if proc.returncode == 0:
            status = 'pass'
        elif proc.returncode == 2:
            status = 'fail'
        elif proc.returncode == 3:
            status = 'skip'
        else:
            status = 'error'

        for log in guest_logs:
            Path(log).unlink(missing_ok=True)
        try:
            g.rsync_from(guest_logs, rsync_opts=('--ignore-missing-args',))
        except subprocess.CalledProcessError as e:
            results.report('error', format_test(test), str(e))
            continue

        results.report(
            status=status,
            name=format_test(test),
            note=proc.stdout.rstrip('\n'),
            logs=[x for x in guest_logs if Path(x).exists()],
        )

results.report_and_exit()

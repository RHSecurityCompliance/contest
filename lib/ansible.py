import os
import sys
import re

from lib import util, versions, results


def install_deps():
    """
    Download and install any external dependencies required for Ansible to run.
    """
    # RHEL-7 and CentOS 7 have these bundled with the base 'ansible' RPM
    if versions.rhel == 7:
        return

    # RHEL has rhc-worker-playbook
    if versions.rhel.is_true_rhel():
        # it should already be installed by test 'recommends' FMF metadata
        util.subprocess_run(
            ['rpm', '--quiet', '-q', 'rhc-worker-playbook'],
            check=True)
        # rhc-worker-playbook modules, exported per official instructions on
        # https://access.redhat.com/articles/remediation
        os.environ['ANSIBLE_COLLECTIONS_PATH'] = \
            '/usr/share/rhc-worker-playbook/ansible/collections/ansible_collections/'

    # CentOS and Fedora need to use ansible-galaxy
    else:
        for collection in ['community.general', 'ansible.posix']:
            util.subprocess_run(
                ['ansible-galaxy', '-vvv', 'collection', 'install', collection],
                check=True)


def report_from_output(lines):
    """
    Process 'ansible-playbook' output, hide useless info, and report important
    info.

    Return True whether there was at least one 'failed' module check.
    This can be used by the caller to differentiate between ansible-playbook
    exit code 2 due to failed checks vs the same exit code due to bad args, etc.
    (False && exit code 2 means a task-unrelated problem.)
    """
    failed = False
    task = '<unknown task>'

    for line in lines:
        # shorten facts
        m = re.match(r'(ok: \[.+\] =>) {"ansible_facts": ', line)
        if m:
            line = f'{m.group(1)} (Redacted by Contest)'

        sys.stdout.write(f'{line}\n')
        sys.stdout.flush()

        # match and parse task name
        m = re.fullmatch(r'TASK \[(.+)\] \*+', line, flags=re.M)
        if m:
            task = m.group(1)
            continue

        # match and parse a module status line
        m = re.fullmatch(r'([\w]+): \[.+\](: [^ ]+)? => (.+)', line)
        if m:
            status, _, data = m.groups()
            if status == 'fatal':
                results.report('error', f'playbook: {task}', data)
                failed = True
            continue

    return failed

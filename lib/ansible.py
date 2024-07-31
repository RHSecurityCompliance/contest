import os
import sys
import re

from lib import util, results


def install_deps():
    """
    Download and install any external dependencies required for Ansible to run.
    """
    # On RHEL, rhc-worker-playbook package should be available and pre-installed
    # by test 'recommends' FMF metadata
    proc = util.subprocess_run(['rpm', '--quiet', '-q', 'rhc-worker-playbook'])
    if proc.returncode == 0:
        # export per official instructions on
        # https://access.redhat.com/articles/remediation
        os.environ['ANSIBLE_COLLECTIONS_PATH'] = \
            '/usr/share/rhc-worker-playbook/ansible/collections/ansible_collections/'
    # Use ansible-galaxy when rhc-worker-playbook not available (Fedora, CentOS, etc.)
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
        m = re.fullmatch(r'TASK \[(.+)\] \*+', line)
        if m:
            task = m.group(1)
            continue

        # match and parse a module status line
        # - note that 'failed:' doesn't use =>
        m = re.fullmatch(r'([\w]+): \[.+\](: [^ ]+)?( =>)? (.+)', line, flags=re.DOTALL)
        if m:
            status, _, _, data = m.groups()
            if status in ['failed', 'fatal']:
                results.report('error', f'playbook: {task}', data)
                failed = True
            continue

    return failed

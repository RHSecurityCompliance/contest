import os
import sys
import re
import contextlib
import subprocess

from lib import util, results, versions

# Versions pinned to match what rhc-worker-playbook bundles on RHEL, so that
# CentOS/Fedora test results stay close to what customers run.
#
# RHEL 8/9 (rhc-worker-playbook 0.1.x):
#   https://gitlab.com/redhat/centos-stream/rpms/rhc-worker-playbook/-/blob/c9s/rhc-worker-playbook.spec
# RHEL 10  (rhc-worker-playbook 0.2.x):
#   https://github.com/RedHatInsights/rhc-worker-playbook/blob/main/ansible/meson.build
ANSIBLE_GALAXY_COLLECTIONS = {
    10: ['ansible.posix:1.5.4', 'community.general:9.2.0'],
    'default': ['ansible.posix:1.3.0', 'community.general:4.4.0'],
}


def install_deps():
    """
    Download and install any external dependencies required for Ansible to run.
    """
    if versions.rhel.is_true_rhel():
        # On RHEL, use collections bundled in rhc-worker-playbook
        # https://access.redhat.com/articles/remediation
        os.environ['ANSIBLE_COLLECTIONS_PATH'] = \
            '/usr/share/rhc-worker-playbook/ansible/collections/ansible_collections/'
    else:
        # On Fedora, CentOS, etc., fetch from Galaxy pinned to RHEL versions
        # Default to RHEL 8/9 collections if no specific version is available
        collections = ANSIBLE_GALAXY_COLLECTIONS.get(
            versions.rhel.major, ANSIBLE_GALAXY_COLLECTIONS['default'],
        )
        util.subprocess_run(
            ['ansible-galaxy', '-vvv', 'collection', 'install', '--force',
             *collections],
            check=True,
            stderr=subprocess.PIPE,
        )


def report_from_output(lines, to_file=None, failure='fail'):
    """
    Process 'ansible-playbook' output, hide useless info, and report important
    info.

    If 'to_file' was specified as a file path, redirect ansible-playbook
    outputs to it, instead of leaving them on the console.

    The 'failure' argument dictates what status to use for failing playbook
    results. The default 'fail' is sensible for uses where the playbook is
    the test itself. If it is not, set it to 'error'.

    Return True whether there was at least one 'failed' module check.
    This can be used by the caller to differentiate between ansible-playbook
    exit code 2 due to failed checks vs the same exit code due to bad args, etc.
    (False && exit code 2 means a task-unrelated problem.)
    """
    failed = False
    task = '<unknown task>'

    with contextlib.ExitStack() as stack:
        if to_file:
            out_file = stack.enter_context(open(to_file, 'w'))
        else:
            out_file = sys.stdout

        for line in lines:
            # shorten facts
            m = re.match(r'(ok: \[.+\] =>) {"ansible_facts": ', line)
            if m:
                line = f'{m.group(1)} (Redacted by Contest)'

            out_file.write(f'{line}\n')
            out_file.flush()

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
                    results.report(failure, f'playbook: {task}', data)
                    failed = True
                continue

    return failed

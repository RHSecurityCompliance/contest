import os
import sys
import re
import contextlib
import subprocess

from lib import util, results, versions

# collections present in the rhc-worker-playbook package and their versions
RHC_WORKER_PLAYBOOK_COLLECTIONS = {
    "community.general": "4.4.0",
    "ansible.posix": "1.3.0",
}


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
        is_centos = versions.rhel.is_centos()
        for collection, version in RHC_WORKER_PLAYBOOK_COLLECTIONS.items():
            if is_centos:
                # install the specific version to match rhc-worker-playbook versions
                collection = f"{collection}:{version}"
            util.subprocess_run(
                ['ansible-galaxy', '-vvv', 'collection', 'install', collection],
                check=True,
                stderr=subprocess.PIPE,
            )


def report_from_output(lines, to_file=None):
    """
    Process 'ansible-playbook' output, hide useless info, and report important
    info.

    If 'to_file' was specified as a file path, redirect ansible-playbook
    outputs to it, instead of leaving them on the console.

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
                    results.report('error', f'playbook: {task}', data)
                    failed = True
                continue

    return failed

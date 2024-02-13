import os

from lib import util, versions


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

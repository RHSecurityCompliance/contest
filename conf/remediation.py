"""
This file contains rules that should NOT be remediated under certain
conditions, as their remediation would lead to a broken OS, unable to
report test results.

Do not use it to exclude expected failures, use the waiving logic instead.
"""

import re

from lib import versions, util


def excludes():
    test_name = util.get_test_name()

    rules = [
        # avoid this globally, so we don't have to change passwords
        # or call 'chage' in every type of remediation
        'accounts_password_set_max_life_existing',
        'accounts_password_set_max_life_root',
    ]

    # Hardenings via Ansible
    if re.fullmatch('/hardening.*/ansible/.*', test_name):
        if versions.rhel.is_centos():
            rules += [
                # https://github.com/ComplianceAsCode/content/issues/8480
                'ensure_redhat_gpgkey_installed',
            ]

    # Host hardenings
    if re.fullmatch('/hardening/host-os/.*', test_name):
        rules += [
            # required by TMT
            'package_rsync_removed',
        ]

    return rules

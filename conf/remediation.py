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
        # also just allow root without -oPermitRootLogin=yes hacks
        'sshd_disable_root_login',
    ]

    # CentOS specific
    if versions.rhel.is_centos():
        rules += [
            # https://github.com/ComplianceAsCode/content/issues/8480
            'ensure_redhat_gpgkey_installed',
            # Testing Farm repositories are without GPG signature
            'ensure_gpgcheck_globally_activated',
            'ensure_gpgcheck_local_packages',
            'ensure_gpgcheck_never_disabled',
            'ensure_gpgcheck_repo_metadata',
            'enable_gpgcheck_for_all_repositories',
        ]
        # Remove when CentOS repos use at least 3072b RSA key
        if versions.rhel in [9,10] and re.fullmatch(r'/hardening/.+/ospp', test_name):
            rules += [
                'configure_crypto_policy',
                'enable_fips_mode',
            ]

    return rules

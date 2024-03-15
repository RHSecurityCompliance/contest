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
    if versions.rhel == 7 and re.fullmatch('/hardening/host-os/.*', test_name):
        rules += [
            # required by TMT, see waivers
            'package_rsync_removed',
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
        ]
        # Remove when CentOS repos use at least 3072b RSA key
        if versions.rhel.major == 9 and re.fullmatch('/hardening/host-os/.*/ospp', test_name):
            rules += [
                'configure_crypto_policy',
                'enable_fips_mode',
            ]
        if versions.rhel.major == 7:
            rules += [
                # On Testing Farm, login as 'root' doesn't work with fips enabled in grub2
                'grub2_enable_fips_mode',
            ]

    return rules

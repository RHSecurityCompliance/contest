# this file contains rules that should NOT be remediated under certain
# conditions, as their remediation would lead to a broken OS, unable to
# report test results
#
# do not use it to exclude expected failures, use the waiving logic instead

import re

from lib import versions, util


excludes = []
test_name = util.get_test_name()

# Hardenings via Ansible
if re.fullmatch('/hardening.*/ansible/.*', test_name):
    if versions.rhel.is_centos():
        excludes += [
            # https://github.com/ComplianceAsCode/content/issues/8480
            'ensure_redhat_gpgkey_installed',
        ]

# Host hardenings
if re.fullmatch('/hardening/host-os/.*', test_name):
    excludes += [
        # required by TMT
        'package_rsync_removed',
    ]

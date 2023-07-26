# this file contains rules that should NOT be remediated under certain
# conditions, as their remediation would lead to a broken OS, unable to
# report test results
#
# do not use it to exclude expected failures, use the waiving logic instead

# skip Ansible remediation for these rules
ansible_skip_tags = [
    # TODO:
    #'ensure_gpgcheck_globally_activated',
    #'ensure_gpgcheck_local_packages',
    #'ensure_gpgcheck_never_disabled',
    #'ensure_gpgcheck_repo_metadata',
    #'ensure_redhat_gpgkey_installed',
    #'no_direct_root_logins',
    #'set_firewalld_default_zone',
    #'firewalld_sshd_disabled',
    #'service_sshd_disabled',
    #'iptables_sshd_disabled',
    #'sshd_disable_root_login',
    #'sshd_disable_empty_passwords',
    #'disable_host_auth',
    #'harden_sshd_crypto_policy',
    #'configure_etc_hosts_deny',
    #'sudo_add_noexec',
    #'accounts_password_set_max_life_existing',
]

# host os "machine hardening" exclusions, the remediation of which would break
# this test suite
host_os = [
    # required by TMT
    'package_rsync_removed',
    # needed by restraint to install a Beaker test RPM containing
    # /distribution/errata/cleanup on the hardened system, because the test RPM
    # doesn't have any signatures
    'ensure_gpgcheck_never_disabled',
]

#!/usr/bin/python3

import re
import subprocess

from lib import results, oscap, versions, podman, util

# following regexes are used to filter rules which are not expected to be evaluated in containers
NA_RULE_PATTERNS = [
    r"kernel_",
    r"sysctl_",
    r"selinux",
    r"mount_",
    r"partition_",
    r"service_",
    r"systemd",
    r"grub2_",
    r"fips_",
    r"sshd_",
    r"audit_",
    r"sudo_",
    r"sudoers_",
    r"dconf_",
    r"fapolicy[d]?_",
    r"usbguard_",
    r"enable_authselect",
]
NA_RULES_REGEX = re.compile("|".join(NA_RULE_PATTERNS))

# select appropriate container image based on host OS
major = versions.rhel.major
minor = versions.rhel.minor
if versions.rhel.is_true_rhel():
    # released RHEL versions have registry.access.redhat.com/ubiX:X.Y images available,
    # for the RHEL y-stream releases in development we just use the latest GA image
    container_image = f'registry.access.redhat.com/ubi{major}:{major}.{minor}'
    try:
        podman.podman('pull', container_image)
    except subprocess.CalledProcessError as e:
        print(f"Error pulling image {container_image}: {e}")
        container_image = f'registry.access.redhat.com/ubi{major}:latest'
        print(f"Pulling the latest GA image {container_image}")
        podman.podman('pull', container_image)
else:
    container_image = f'quay.io/centos/centos:stream{major}'
    podman.podman('pull', container_image)

proc, lines = util.subprocess_stream(
    [
        'oscap-podman', container_image, 'xccdf', 'eval', '--profile', '(all)', '--progress',
        '--report', 'report.html', '--results-arf', 'scan-arf.xml', util.get_datastream(),
    ],
    stderr=subprocess.STDOUT,
)

for line in lines:
    if match := oscap.rule_from_verbose(line):
        rulename, status = match
        if status in ['error', 'unknown']:
            results.report('error', rulename, f'scanner returned: {status}')
        elif NA_RULES_REGEX.match(rulename) and status != 'notapplicable':
            results.report('fail', rulename, f'expected notapplicable, scanner returned: {status}')
        else:
            results.report('pass', rulename, f'scanner returned: {status}')

if proc.returncode not in [0,2]:
    raise RuntimeError("oscap failed unexpectedly")

util.subprocess_run(['gzip', '-9', 'scan-arf.xml'], check=True, stderr=subprocess.PIPE)

results.report_and_exit(logs=['report.html', 'scan-arf.xml.gz'])

#!/usr/bin/python3

import re
import subprocess

from lib import util, results, versions

syscalls_groups = [
    ['setxattr', 'lsetxattr', 'fsetxattr', 'removexattr', 'lremovexattr', 'fremovexattr'],
    ['init_module', 'delete_module', 'query_module', 'finit_module'],
    ['open', 'creat', 'truncate', 'ftruncate', 'openat', 'open_by_handle_at'],
    ['lchown', 'fchown', 'chown', 'fchownat'],
    ['adjtimex', 'settimeofday'],
    ['clock_settime'],
    ['sethostname', 'setdomainname'],
]
# fchmodat2 is only available since RHEL 10+ kernels,
# CaC/content rule for renameat2 is only on RHEL 10+
if versions.rhel >= 10:
    syscalls_groups.append(['chmod', 'fchmod', 'fchmodat', 'fchmodat2'])
    syscalls_groups.append(['unlink', 'unlinkat', 'rename', 'renameat', 'renameat2', 'rmdir'])
else:
    syscalls_groups.append(['chmod', 'fchmod', 'fchmodat'])
    syscalls_groups.append(['unlink', 'unlinkat', 'rename', 'renameat', 'rmdir'])


def syscalls_pretty_print(syscalls):
    return ','.join(syscalls)


def unselect_all_rules_except_audit(orig_ds, new_ds):
    rule_line = re.compile(r'<[^>]*Rule[^>]*\bid="xccdf_org.ssgproject.content_rule_')
    audit_rules = re.compile(
        r'<.*Rule.*id="xccdf_org.ssgproject.content_rule_audit_rules.*'
        r'(_unsuccessful_file_modification|_dac_modification|'
        r'_file_deletion_events|_kernel_module_loading|'
        r'_networkconfig_modification|_time_adjtimex|'
        r'_time_clock_settime|_time_settimeofday|_time_stime)',
    )

    with open(orig_ds) as orig_ds_f, open(new_ds, 'w') as new_ds_f:
        for line in orig_ds_f:
            if rule_line.search(line):
                if audit_rules.search(line):
                    line = line.replace('selected="false"', 'selected="true"')
                else:
                    line = line.replace('selected="true"', 'selected="false"')
            new_ds_f.write(line)


def verify_syscalls_grouped_in_audit_rules(audit_syscalls, audit_rules_file):
    util.log(f"Searching for audit syscalls group: {syscalls_pretty_print(audit_syscalls)}")
    util.log("Matching audit rules:")
    # create regex patterns for each syscall - match word boundaries to avoid partial matches
    syscall_patterns = [fr'\b{syscall}\b' for syscall in audit_syscalls]

    match_found = False
    with open(audit_rules_file) as f:
        for line in f:
            # check if all syscalls from the group are present in the line
            if all(re.search(pattern, line) for pattern in syscall_patterns):
                match_found = True
                util.log(line.strip())

    if not match_found:
        util.log("No matching audit rules found!")

    return match_found


unselect_all_rules_except_audit(util.get_datastream(), 'remediation-ds.xml')

util.backup('/etc/audit')
try:
    cmd = [
        'oscap', 'xccdf', 'eval', '--progress', '--remediate', '--report', 'report.html',
        '--results-arf', 'remediation-arf.xml', 'remediation-ds.xml',
    ]
    util.subprocess_run(cmd, check=True, stderr=subprocess.PIPE)
    results.add_log('remediation-arf.xml', 'report.html')

    util.subprocess_run(['augenrules', '--load'], check=True, stderr=subprocess.PIPE)

    with open('audit_rules.txt', 'w') as f:
        util.subprocess_run(
            ['auditctl', '-l'], stdout=f, text=True, check=True, stderr=subprocess.PIPE,
        )
    results.add_log('audit_rules.txt')
finally:
    util.restore('/etc/audit')
    util.subprocess_run(['augenrules', '--load'], check=True, stderr=subprocess.PIPE)

for group in syscalls_groups:
    if verify_syscalls_grouped_in_audit_rules(group, 'audit_rules.txt'):
        results.report('pass', syscalls_pretty_print(group))
    else:
        results.report('fail', syscalls_pretty_print(group))

results.report_and_exit()

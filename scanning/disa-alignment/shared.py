import re

from lib import results, versions


profile = 'stig'
profile_full = f'xccdf_org.ssgproject.content_profile_{profile}'

# RHEL-7 HTML report doesn't contain OVAL findings by default
oval_results = '' if versions.oscap >= 1.3 else '--results results.xml --oval-results'

shared_cmd = ['oscap', 'xccdf', 'eval', '--progress', oval_results]


def content_scan(host, ds, html, arf):
    """
    Scan machine and prepare ARF results for STIG Viewer.
    Return HTML report and ARF file.
    """
    cmd = [
        *shared_cmd,
        '--profile', profile_full,
        '--report', html,
        '--stig-viewer', arf,
        ds,
    ]
    proc = host.ssh(' '. join(cmd))
    if proc.returncode not in [0,2]:
        raise RuntimeError(f"remediation oscap failed with {proc.returncode}")


def disa_scan(host, ds, html, arf):
    """
    Scan machine with datastream without profiles via '--profile (all)'.
    Return HTML report and ARF file.
    """
    cmd = [
        *shared_cmd,
        '--profile', '\'(all)\'',
        '--report', html,
        '--results-arf', arf,
        ds,
    ]
    proc = host.ssh(' '. join(cmd))
    if proc.returncode not in [0,2]:
        raise RuntimeError(f"remediation oscap failed with {proc.returncode}")


def comparison_report(comparison_output):
    """
    Parse CaC/content utils/compare_results.py output and report different results.
      Same result format:      CCE CCI - DISA_RULE_ID SSG_RULE_ID     RESULT
      Different result format: CCE CCI - DISA_RULE_ID SSG_RULE_ID     SSG_RESULT - DISA_RESULT
    """
    result_regex = re.compile(r'([\w-]+) [\w-]+ - [\w-]+ (\w*)\s+(\w+)(?: - *(\w+))*')
    for match in result_regex.finditer(comparison_output):
        rule_cce, rule_id, ssg_result, disa_result = match.groups()
        if not rule_id:
            rule_id = rule_cce
        # Only 1 result matched - same results
        if not disa_result:
            results.report('pass', rule_id)
        # SSG CPE checks can make rule notapplicable by different reason (package not
        # installed, architecture, RHEL version). DISA bechmark doesn't have this
        # capability, it just 'pass'. Ignore such result misalignments
        elif ssg_result == 'notapplicable' and disa_result == 'pass':
            result_note = 'SSG result: notapplicable, DISA result: pass'
            results.report('pass', rule_id, result_note)
        # Different results
        else:
            result_note = f'SSG result: {ssg_result}, DISA result: {disa_result}'
            results.report('fail', rule_id, result_note)

import collections
import enum
import xml.etree.ElementTree as ET

from lib import results

nsmap = {
    "xccdf": "http://checklists.nist.gov/xccdf/1.2",
}
STIG_REF = "https://public.cyber.mil/stigs/srg-stig-tools/"
CCE = "https://ncp.nist.gov/cce"
SSG_RULE_PREFIX = "xccdf_org.ssgproject.content_rule_"
DISA_RULE_PREFIX = "xccdf_mil.disa.stig_rule_"

DISARuleResult = collections.namedtuple('DISARuleResult', ['rule_id', 'result'])

profile = 'stig'

shared_cmd = ['oscap', 'xccdf', 'eval', '--progress']


class SSGRuleResult:
    def __init__(self, rule_id, cce_id, rule_title, stig_ids, result):
        self.rule_id = rule_id
        self.cce_id = cce_id
        self.rule_title = rule_title
        self.stig_ids = stig_ids
        self.result = result
        self.stig_ids_results = {}
        self.final_result = None

    def __repr__(self):
        return (
            f"SSGRuleResult(rule_id='{self.rule_id}', cce_id='{self.cce_id}',"
            f"rule_title='{self.rule_title}', stig_ids={self.stig_ids}', "
            f"result='{self.result}', "
            f"comparison_with_stig_ids={self.stig_ids_results}, "
            f"final_result={self.final_result})"
        )


class ComparisonResult(enum.Enum):
    SAME = enum.auto()
    DIFFERENT = enum.auto()
    MISSING = enum.auto()


def content_scan(host, ds, html, arf):
    """
    Scan machine and prepare ARF results for STIG Viewer.
    Return HTML report and ARF file.
    """
    cmd = [
        *shared_cmd,
        '--profile', profile,
        '--report', html,
        '--results-arf', arf,
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


def parse_ssg_results(ssg_path):
    ssg_results = {}
    root = ET.parse(ssg_path).getroot()
    xccdf_benchmark = root.find(".//xccdf:Benchmark", nsmap)
    xccdf_results = root.find(".//xccdf:TestResult", nsmap)
    for rule_result in xccdf_results.findall("xccdf:rule-result", nsmap):
        full_rule_id = rule_result.get("idref")
        result = rule_result.find("xccdf:result", nsmap).text
        if result == "notselected":
            continue
        rule = xccdf_benchmark.find(
            f".//xccdf:Rule[@id='{full_rule_id}']", nsmap)
        title = rule.find("xccdf:title", nsmap).text
        cce_id = rule.find(f"xccdf:ident[@system='{CCE}']", nsmap).text
        stig_ids = []
        xpath = f"xccdf:reference[@href='{STIG_REF}']"
        for stig_ref_el in rule.findall(xpath, nsmap):
            if stig_ref_el is not None:
                stig_ids.append(stig_ref_el.text)
        rule_id = full_rule_id.replace(SSG_RULE_PREFIX, "")
        sr = SSGRuleResult(rule_id, cce_id, title, stig_ids, result)
        ssg_results[rule_id] = sr
    return ssg_results


def parse_disa_results(disa_path):
    disa_results = {}
    root = ET.parse(disa_path).getroot()
    xccdf_results = root.find(".//xccdf:TestResult", nsmap)
    for rule_result in xccdf_results.findall("xccdf:rule-result", nsmap):
        full_rule_id = rule_result.get("idref")
        rule_id = full_rule_id.replace(DISA_RULE_PREFIX, "")
        result = rule_result.find("xccdf:result", nsmap).text
        disa_results[rule_id] = result
    return disa_results


def compare_result_with_stig_id(result, stig_id, disa_results):
    if stig_id in disa_results:
        disa_result = disa_results[stig_id]
        if result == disa_result:
            return ComparisonResult.SAME
        else:
            return ComparisonResult.DIFFERENT
    else:
        return ComparisonResult.MISSING


def compare_results(ssg_results, disa_results):
    for ssg_rule_result in ssg_results.values():
        same = 0
        different = 0
        missing = 0
        if len(ssg_rule_result.stig_ids) == 0:
            ssg_rule_result.final_result = ComparisonResult.MISSING
        for stig_id in ssg_rule_result.stig_ids:
            comparison_result = compare_result_with_stig_id(
                ssg_rule_result.result, stig_id, disa_results)
            disa_result = disa_results.get(stig_id, "not found")
            ssg_rule_result.stig_ids_results[stig_id] = disa_result
            if comparison_result == ComparisonResult.SAME:
                same += 1
            elif comparison_result == ComparisonResult.DIFFERENT:
                different += 1
            elif comparison_result == ComparisonResult.MISSING:
                missing += 1
        if same >= 1:
            ssg_rule_result.final_result = ComparisonResult.SAME
        elif different >= 1:
            ssg_rule_result.final_result = ComparisonResult.DIFFERENT
        elif missing >= 1:
            ssg_rule_result.final_result = ComparisonResult.MISSING


def get_disa_result_to_str(stig_ids_results):
    if len(stig_ids_results) == 0:
        return "Empty"
    ll = (f"{k}:{v}" for k, v in stig_ids_results.items())
    return ", ".join(ll)


def print_ssg_results(ssg_results):
    print(
        "Alignment CCE         Rule ID               Result                "
        "Stig ID:DISA Result")
    for ssg_result in ssg_results.values():
        disa = get_disa_result_to_str(ssg_result.stig_ids_results)
        print(
            f"{ssg_result.final_result:<10}"
            f"{ssg_result.cce_id} "
            f"{ssg_result.rule_id:<55} "
            f"{ssg_result.result:<20} "
            f"{disa}")


def report_misalignments(ssg_results):
    # SSG CPE checks can make rule notapplicable by different reason (package
    # not installed, architecture, RHEL version). DISA benchmark doesn't have
    # this capability, it just 'pass'. Ignore such result misalignments.
    for ssg_result in ssg_results.values():
        result = "pass"
        disa = get_disa_result_to_str(ssg_result.stig_ids_results)
        result_note = f"SSG result: {ssg_result.result}, DISA result(s): {disa}"
        if ssg_result.final_result == ComparisonResult.DIFFERENT and \
                ssg_result.result != "notapplicable":
            result = "fail"
        results.report(result, ssg_result.rule_id, result_note)


def compare_arfs(ssg_path, disa_path):
    ssg_results = parse_ssg_results(ssg_path)
    disa_results = parse_disa_results(disa_path)
    compare_results(ssg_results, disa_results)
    print_ssg_results(ssg_results)
    report_misalignments(ssg_results)

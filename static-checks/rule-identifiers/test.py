#!/usr/bin/python3

from collections import defaultdict

from lib import util, results, oscap

# reference names taken from
# https://github.com/ComplianceAsCode/content/blob/master/ssg/constants.py
profile_references = {
    # srg, disa, stigid@PRODUCT or controls file
    'stig': {
        'stigid': 'https://public.cyber.mil/stigs/downloads/?_dl_facet_stigs=operating-systems%2Cunix-linux',
        'os-srg': 'https://public.cyber.mil/stigs/downloads/?_dl_facet_stigs=operating-systems%2Cgeneral-purpose-os',
    },
    # ospp
    'ospp': {
        'ospp': 'https://www.niap-ccevs.org/Profile/PP.cfm',
    },
    # cis@PRODUCT or controls file
    'cis': {
        'cis': 'https://www.cisecurity.org/benchmark/red_hat_linux/',
    },
    # anssi_bp28_high (controls file)
    'anssi_bp28_high': {
        'anssi': 'https://cyber.gouv.fr/sites/default/files/document/linux_configuration-en-v2.pdf',
    },
    # ism
    'ism_o': {
        'ism': 'https://www.cyber.gov.au/acsc/view-all-content/ism',
    },
    # hipaa
    'hipaa': {
        'hipaa': 'https://www.gpo.gov/fdsys/pkg/CFR-2007-title45-vol1/pdf/CFR-2007-title45-vol1-chapA-subchapC.pdf',
    },
    # pcidss4
    'pci-dss': {
        'pcidss4': 'https://docs-prv.pcisecuritystandards.org/PCI%20DSS/Standard/PCI-DSS-v4_0.pdf',
    },
}

profiles = oscap.global_ds().profiles

# Parse from datastream all rules and all their references
rule_references = defaultdict(set)
for frames, elements in oscap.parse_xml(util.get_datastream()):
    if len(frames) < 3 or frames[-3:] != ['Group', 'Rule', 'reference']:
        continue

    rule, reference = elements[-2:]
    rule = rule.get('id').removeprefix('xccdf_org.ssgproject.content_rule_')
    reference = reference.get('href')
    rule_references[rule].add(reference)

for ref_profile, nested in profile_references.items():
    for ref_name, ref_url in nested.items():
        for rule in profiles[ref_profile].rules:
            result_name = f'{ref_profile}/{ref_name}/{rule}'
            if ref_url in rule_references[rule]:
                results.report('pass', result_name)
            else:
                results.report('fail', result_name, f"missing {ref_url}")

results.report_and_exit()

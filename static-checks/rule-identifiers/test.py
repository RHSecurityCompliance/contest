#!/usr/bin/python3

import re
from collections import defaultdict

from lib import util, results, oscap


profile_references = {
    # srg, disa, stigid@PRODUCT or controls file
    'stig': [
        'https://public.cyber.mil/stigs/downloads/?_dl_facet_stigs=operating-systems%2Cgeneral-purpose-os',
        'https://public.cyber.mil/stigs/cci/',
        'https://public.cyber.mil/stigs/downloads/?_dl_facet_stigs=operating-systems%2Cunix-linux',
    ],
    # ospp
    'ospp': ['https://www.niap-ccevs.org/Profile/PP.cfm'],
    # cis@PRODUCT or controls file
    'cis': ['https://www.cisecurity.org/benchmark/red_hat_linux/'],
    # anssi (controls file)
    'anssi': ['https://cyber.gouv.fr/sites/default/files/document/linux_configuration-en-v2.pdf'],
    # ism
    'ism_o': ['https://www.cyber.gov.au/acsc/view-all-content/ism'],
    # hipaa
    'hipaa': ['https://www.gpo.gov/fdsys/pkg/CFR-2007-title45-vol1/pdf/CFR-2007-title45-vol1-chapA-subchapC.pdf'],
    # pcidss4
    'pci-dss': ['https://docs-prv.pcisecuritystandards.org/PCI%20DSS/Standard/PCI-DSS-v4_0.pdf'],
}


profiles = oscap.global_ds().profiles
# Parse from datastream all rules and all their references
rule_references = defaultdict(set)
for frames, elements in oscap.parse_xml(util.get_datastream()):
    if len(frames) < 3 or frames[-3:] != ['Group', 'Rule', 'reference']:
        continue

    rule, reference = elements[-2:]
    # TODO: use str.removeprefix on python 3.9+
    rule = re.sub('^xccdf_org.ssgproject.content_rule_', '', rule.get('id'))
    reference = reference.get('href')
    rule_references[rule].add(reference)

for profile, references in profile_references.items():
    for rule in profiles[profile].rules:
        for reference in references:
            if reference in rule_references[rule]:
                results.report('pass', f'{profile}/{rule}')
            else:
                results.report('fail', f'{profile}/{rule}', f"missing {reference}")

results.report_and_exit()

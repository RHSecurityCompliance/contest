#!/usr/bin/python3

from collections import defaultdict

from lib import util, results, oscap, versions

reference_urls = {}
for frames, elements in oscap.parse_xml(util.get_datastream()):
    if len(frames) >= 2 and frames[-2:] == ['Benchmark', 'reference']:
        name = elements[-1].text
        href = elements[-1].get('href')
        if name and href:
            reference_urls[name] = href

# Associations between profiles and reference names
profile_reference_names = {
    'bsi': ['bsi'],
    'stig': ['stigid', 'os-srg', 'stigref'],
    'ospp': ['ospp'],
    'cis': ['cis'],
    'anssi_bp28_high': ['anssi'],
    'hipaa': ['hipaa'],
    'pci-dss': ['pcidss4'],
}
if versions.rhel == 9:
    profile_reference_names['ccn_advanced'] = ['ccn']
if versions.rhel <= 9:
    profile_reference_names['ism_o'] = ['ism']
else:
    profile_reference_names['ism_o_top_secret'] = ['ism']

# Resolve the per-profile references to URLs using the datastream-derived mapping
profile_references = {}
for profile, ref_names in profile_reference_names.items():
    nested = {}
    for ref_name in ref_names:
        if ref_name in reference_urls:
            nested[ref_name] = reference_urls[ref_name]
        else:
            results.report(
                'error',
                f'{profile}/{ref_name}',
                'reference not found in datastream',
            )
    profile_references[profile] = nested

profiles = oscap.global_ds().profiles

# Parse from datastream all rules and all their references
rule_references = defaultdict(set)
# Collect stigid text values
rule_stigid_text = {}

for frames, elements in oscap.parse_xml(util.get_datastream()):
    if len(frames) < 3 or frames[-3:] != ['Group', 'Rule', 'reference']:
        continue

    rule, reference = elements[-2:]
    rule_id = rule.get('id').removeprefix('xccdf_org.ssgproject.content_rule_')
    ref_href = reference.get('href')
    ref_text = reference.text

    rule_references[rule_id].add(ref_href)

    # Store the control ID
    if ref_text and 'stigs/downloads' in ref_href:
        rule_stigid_text[rule_id] = ref_text

for ref_profile, nested in profile_references.items():
    if ref_profile not in profiles:
        results.report('skip', ref_profile)
        continue

    for ref_name, ref_url in nested.items():
        for rule in profiles[ref_profile].rules:
            # Skip rules from 'needed_rules' controls - they don't have actual requirement IDs
            if rule in rule_stigid_text and rule_stigid_text[rule] == 'needed_rules':
                continue

            result_name = f'{ref_profile}/{ref_name}/{rule}'
            if ref_url in rule_references[rule]:
                results.report('pass', result_name)
            else:
                results.report('fail', result_name, f'missing {ref_url}')

results.report_and_exit()

#!/usr/bin/python3

import re
import platform
import tempfile
import difflib
import yaml
from pathlib import Path

from lib import util, results, oscap


# extract audit rules filepaths + contents from the datastream XML
def get_ds_remediations():
    remediations = dict()
    for frames, elements in oscap.parse_xml(util.get_datastream()):
        if len(frames) < 3 or frames[-3:] != ['Group', 'Rule', 'fix']:
            continue

        group, rule, fix = elements[-3:]
        # TODO: use str.removeprefix on python 3.9+
        group_name = re.sub('^xccdf_org.ssgproject.content_group_', '', group.get('id'))
        # TODO: use str.removeprefix on python 3.9+
        rule_name = re.sub('^xccdf_org.ssgproject.content_rule_', '', rule.get('id'))

        # only rules in the policy_rules group
        if group_name != 'policy_rules':
            continue
        # skip non-ansible remediations
        if fix.get('system') != 'urn:xccdf:fix:script:ansible':
            continue

        content = yaml.safe_load(fix.text)

        # try to find a playbook section with audit contents
        try:
            section = next(
                s for s in content if 'name' in s and s['name'].startswith('Put contents ')
            )
        except StopIteration:
            results.report('error', rule_name, 'could not find relevant remediation section')
            continue

        # do extra sanity checking to get a reasonable error message
        if 'copy' not in section or any(k not in section['copy'] for k in ['dest','content']):
            results.report('error', rule_name, 'copy playbook section or dest/content not found')
            continue

        copy = section['copy']
        remediations[rule_name] = (Path(copy['dest']), copy['content'])

    return remediations


def delete_foreign_arches(remediations):
    arch = platform.machine()
    for rule in list(remediations):
        # already removed
        if rule not in remediations:
            continue
        # find all "variants" (per-arch specific) rules for the given rule
        variants = {var for var in remediations if var != rule and var.startswith(rule)}
        if variants:
            # if there is a variant specific for the current arch, delete all
            # other variants including the arch-less rule,
            if f'{rule}_{arch}' in variants:
                variants.remove(f'{rule}_{arch}')
                for var in variants:
                    del remediations[var]
                del remediations[rule]
            # else keep just the arch-less rule, delete all architecture variants
            else:
                for var in variants:
                    del remediations[var]


def report_diff(*args, ds_contents, sample_contents, filename, **kwargs):
    # label --- and +++ with nice and understandable names
    diff = difflib.unified_diff(
        ds_contents.splitlines(),
        sample_contents.splitlines(),
        fromfile=f'remediated-datastream/{filename}',
        tofile=f'shipped-with-audit/{filename}',
        n=0,
        lineterm='',
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        diff_file = tmpdir / 'diff.txt'
        with open(diff_file, 'w') as f:
            for line in diff:
                f.write(f'{line}\n')
        results.report(*args, **kwargs, logs=[diff_file])


audit_sample_dir = Path('/usr/share/audit/sample-rules')
audit_sample_files = {f.name for f in audit_sample_dir.iterdir()}

remediations = get_ds_remediations()
delete_foreign_arches(remediations)

# report findings rule-by-rule, put file basename in the note
for rule_name, values in remediations.items():
    filepath, ds_contents = values

    if filepath.name not in audit_sample_files:
        results.report('fail', rule_name, f'{filepath.name} is not shipped with audit')
        continue

    sample_contents = (audit_sample_dir / filepath.name).read_text()
    if ds_contents != sample_contents:
        report_diff(
            'fail', rule_name, f'{filepath.name} changed',
            ds_contents=ds_contents, sample_contents=sample_contents, filename=filepath.name,
        )
    else:
        results.report('pass', rule_name, filepath.name)

results.report_and_exit()

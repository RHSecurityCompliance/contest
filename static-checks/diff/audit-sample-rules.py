#!/usr/bin/python3

import re
import tempfile
import difflib
import yaml
from pathlib import Path

from lib import util, results, versions, oscap


# extract audit rules filepaths + contents from the datastream XML
def get_ds_remediations():
    remediations = {}
    for frames, elements in oscap.parse_xml(util.get_datastream()):
        if len(frames) < 3 or frames[-3:] != ['Group', 'Rule', 'fix']:
            continue

        group, rule, fix = elements[-3:]
        # TODO: use str.removeprefix on python 3.9+
        group_name = re.sub(r'^xccdf_org.ssgproject.content_group_', '', group.get('id'))
        # TODO: use str.removeprefix on python 3.9+
        rule_name = re.sub(r'^xccdf_org.ssgproject.content_rule_', '', rule.get('id'))

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


def delete_notapplicable(remediations):
    # get --rule rule_name --rule another_rule ... pairs of CLi options
    rule_prefix = 'xccdf_org.ssgproject.content_rule_'
    rule_pairs = (pair for rule in remediations for pair in ('--rule', f'{rule_prefix}{rule}'))
    # run oscap to figure out which rules are relevant for the current OS,
    # ignoring any scan pass/fail results
    proc, lines = util.subprocess_stream([
        'oscap', 'xccdf', 'eval', '--profile', '(all)', '--progress', *rule_pairs,
        util.get_datastream(),
    ])
    # delete notapplicable rules
    for rule_name, status in oscap.rules_from_verbose(lines):
        if status == 'notapplicable' and rule_name in remediations:
            del remediations[rule_name]
    # ensure we had valid results above
    if proc.returncode not in [0,2]:
        raise RuntimeError(f"scanning with oscap failed with {proc.returncode}")


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


if versions.rhel >= 10:
    # https://github.com/linux-audit/audit-userspace/commit/eb2b95f23
    # provided by a new audit-rules package
    audit_sample_dir = Path('/usr/share/audit-rules')
else:
    audit_sample_dir = Path('/usr/share/audit/sample-rules')

audit_sample_files = {f.name for f in audit_sample_dir.iterdir()}

remediations = get_ds_remediations()
delete_notapplicable(remediations)

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

results.report_and_exit()

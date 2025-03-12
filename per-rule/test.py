#!/usr/bin/python3

import os
import re
import shutil
import inspect
import tempfile
import subprocess
import collections
from pathlib import Path

from lib import util, results, versions, virt, oscap, unit_tests
from conf import remediation


## /per-rule/from-env/oscap --> test_basename=from-env, fix_type=oscap
#test_basename, fix_type = util.get_test_name().rsplit('/')[-2:]
#if test_basename == 'from-env':
#    our_rules = os.environ.get('RULE')
#    if our_rules:
#        our_rules = our_rules.split()  # space-separated
#    else:
#        raise RuntimeError("RULE env variable not defined or empty")
#else:
#    all_rules = sorted(oscap.global_ds().get_all_profiles_rules())
#    start = int(test_basename) - 1
#    total = int(os.environ['TOTAL_SLICES'])
#    # slice all_rules, get every total-th member
#    our_rules = all_rules[start::total]



_, variant = util.get_test_name().rsplit('/', 1)

# directory containing this test.py; necessary because we run in a tmpdir
testdir = Path(inspect.getfile(inspect.currentframe())).parent

virt.Host.setup()

remediation_excludes = set(remediation.excludes())

#with util.get_source_content() as content_dir, tempfile.TemporaryDirectory() as tmpdir:
with util.get_source_content() as content_dir:
#    # thin datastreams cannot be built alongside other content, build them first
#    # (separately), move aside the XMLs
#    util.build_content(
#        content_dir,
#        {
#            'SSG_THIN_DS:BOOL': 'ON',
#            'SSG_THIN_DS_RULE_ID:STRING': 'ALL_RULES',
#        },
#        make_targets=('generate-ssg-rhel9-ds.xml',),
#        force=True,
#    )
#    build_dir = content_dir / util.CONTENT_BUILD_DIR
#    product_dir = build_dir / f'rhel{versions.rhel.major}'
#    thin_ds_dir = build_dir / 'thin_ds'
#    new_thin_ds_dir = Path(tmpdir) / 'thin_ds'
#    #shutil.move(thin_ds_dir, new_thin_ds_dir)
#    #thin_ds_dir = new_thin_ds_dir
#
#    # then rebuild the content, with normal datastream + other artifacts
#    util.build_content(
#        content_dir,
#        {
#            'SSG_BUILT_TESTS_ENABLED:BOOL': 'ON',
#            'SSG_ANSIBLE_PLAYBOOKS_PER_RULE_ENABLED:BOOL': 'ON',
#        },
#        force=True,
#    )
#    ds_path = util.get_datastream(content_dir=content_dir)
#    ds = oscap.Datastream(ds_path)
#    built_tests = product_dir / 'tests'
#    playbooks_dir = util.find_per_rule_playbooks(content_dir=content_dir)

    # thin datastreams cannot be built alongside other content, build them first
    # (separately), move aside the XMLs
    util.build_content(
        content_dir,
        {
            'SSG_THIN_DS:BOOL': 'ON',
            'SSG_THIN_DS_RULE_ID:STRING': 'ALL_RULES',
            'SSG_BUILT_TESTS_ENABLED:BOOL': 'ON',
            'SSG_ANSIBLE_PLAYBOOKS_PER_RULE_ENABLED:BOOL': 'ON',
        },
#        force=True,
    )
    build_dir = content_dir / util.CONTENT_BUILD_DIR
    product_dir = build_dir / f'rhel{versions.rhel.major}'
    thin_ds_dir = build_dir / 'thin_ds'

    ds_path = util.get_datastream(content_dir=content_dir)
    ds = oscap.Datastream(ds_path)
    built_tests = product_dir / 'tests'
    playbooks_dir = util.find_per_rule_playbooks(content_dir=content_dir)

    all_rules = sorted(ds.get_all_profiles_rules())
    util.log(f"will be testing {len(all_rules)} rules")

    ssg_ds_prefix = f'ssg-rhel{versions.rhel.major}-ds_'
    for file in thin_ds_dir.iterdir():
        file.rename(file.parent / file.name.removeprefix(ssg_ds_prefix))

    unit_tests = list(collect_unit_tests(all_rules, built_tests))
    from pprint import pformat
    util.log(pformat(list(unit_tests)))

    # collect all packages from all unit_tests
    packages = {pkg for t in unit_tests if t.packages is not None for pkg in t.packages}

    # install a VM
    ks = virt.Kickstart()
    ks.packages += ['rsync', 'xmlstarlet']
    g = virt.Guest('per_rule')  # TODO: temp for debugging, use empty () on final
    g.install(kickstart=ks)

    with g.booted(safe_shutdown=True):
        # install extra test dependencies now
        # (Anaconda seems to crash with some of these, hence install-after-boot)
        g.ssh('dnf install -y --skip-broken', *packages, check=True)
        # copy built artifacts to the guest
        g.rsync_to(ds_path, 'ds.xml')
        g.rsync_to(f'{thin_ds_dir}/', 'thin_ds')
        g.rsync_to(f'{built_tests}/', 'tests')
        g.rsync_to(f'{playbooks_dir}/', 'playbooks')
        # copy guest runner
        g.rsync_to(testdir / 'runner.sh')

    g.prepare_for_snapshot()

#for unit_test in unit_tests:
#    # TODO: parse rule, test name, assemble test file, etc.
#
##rule=$1             # some_rule_name
##test_name=$2        # some_test_name
##test_type=$3        # pass or fail
##remediation=$4      # bash or ansible or none
##variables="${@:5}"  # key=value key2=value2 ...
#
#
#    with g.snapshotted():
#        proc = g.ssh(
#			'./runner.sh',
#			unit_test.rule,
#			unit_test.test,
#			'pass' if unit_test.is_pass else 'fail',
#			'oscap' if variant == 'oscap' else 'ansible',
#            *(unit_test.variables or ()),
#            stderr=subprocess.PIPE,
#		)
#        ...
#        # rsync takes space-separated files in since remote source arg
#        # TODO: pass --ignore-missing-args somehow
#        g.rsync_from('runner.log test.log results-arf.xml')
#        







#with g.snapshotted():
#    # copy our datastream to the guest
#    oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())
#    g.copy_to('remediation-ds.xml')
#
#    # - remediate twice due to some rules being 'notapplicable'
#    #   on the first pass
#    for arf_results in ['remediation-arf.xml', 'remediation2-arf.xml']:
#        cmd = [
#            'oscap', 'xccdf', 'eval', '--profile', profile,
#            '--progress', '--results-arf', arf_results,
#            '--remediate', 'remediation-ds.xml',
#        ]
#        proc = g.ssh(' '.join(cmd))
#        if proc.returncode not in [0,2]:
#            raise RuntimeError(f"remediation oscap failed with {proc.returncode}")
#        g.soft_reboot()
#
#    # copy the original DS to the guest
#    g.copy_to(util.get_datastream(), 'scan-ds.xml')
#    # scan the remediated system
#    proc, lines = g.ssh_stream(
#        f'oscap xccdf eval --profile {profile} --progress --report report.html'
#        f' --results-arf scan-arf.xml scan-ds.xml',
#    )
#    oscap.report_from_verbose(lines)
#    if proc.returncode not in [0,2]:
#        raise RuntimeError("post-reboot oscap failed unexpectedly")
#
#    g.copy_from('report.html')
#    g.copy_from('remediation-arf.xml')
#    g.copy_from('remediation2-arf.xml')
#    g.copy_from('scan-arf.xml')
#
#tar = [
#    'tar', '-cvJf', 'results-arf.tar.xz',
#    'remediation-arf.xml', 'remediation2-arf.xml', 'scan-arf.xml',
#]
#util.subprocess_run(tar, check=True)
#
#logs = [
#    'report.html',
#    'results-arf.tar.xz',
#]
#results.report_and_exit(logs=logs)


results.report_and_exit()

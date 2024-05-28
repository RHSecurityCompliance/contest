#!/usr/bin/python3

from lib import util, results, oscap

new = oscap.global_ds()

with util.get_old_datastream() as old_xml:
    old = oscap.Datastream(old_xml)

    common_profiles = set(new.profiles).intersection(old.profiles)

    for profile in sorted(common_profiles):
        old_rules = set(old.profiles[profile].rules)
        new_rules = set(new.profiles[profile].rules)
        for rule in sorted(old_rules - new_rules):
            results.report('fail', f'{profile}/-{rule}')
        for rule in sorted(new_rules - old_rules):
            results.report('fail', f'{profile}/+{rule}')

results.report_and_exit()

#!/usr/bin/python3

from lib import util, results, oscap

new = oscap.global_ds()

with util.get_old_datastream() as old_xml:
    util.log(f"comparing OLD: {old_xml} to NEW: {new.path}")
    old = oscap.Datastream(old_xml)
    old_profiles = set(old.profiles)
    new_profiles = set(new.profiles)

    for profile in sorted(old_profiles - new_profiles):
        results.report('fail', f'-{profile}')
    for profile in sorted(new_profiles - old_profiles):
        results.report('fail', f'+{profile}')

results.report_and_exit()

#!/usr/bin/python3

from lib import util, results, oscap

new = oscap.global_ds()

with util.get_old_datastream() as old_xml:
    util.log(f"comparing OLD: {old_xml} to NEW: {new.path}")
    old = oscap.Datastream(old_xml)

    common_profiles = set(new.profiles).intersection(old.profiles)

    for profile in sorted(common_profiles):
        old_title = old.profiles[profile].title
        new_title = new.profiles[profile].title
        if old_title != new_title:
            results.report('info', f'{profile}/-{old_title}')
            results.report('info', f'{profile}/+{new_title}')

results.report_and_exit()

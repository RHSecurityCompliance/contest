#!/usr/bin/python3

import shared
from lib import results, oscap

new = oscap.global_ds()

with shared.get_old_datastream() as old_xml:
    old = oscap.Datastream(old_xml)
    old_profiles = set(old.profiles)
    new_profiles = set(new.profiles)

    for profile in sorted(old_profiles - new_profiles):
        results.report('fail', f'-{profile}')
    for profile in sorted(new_profiles - old_profiles):
        results.report('fail', f'+{profile}')

results.report_and_exit()

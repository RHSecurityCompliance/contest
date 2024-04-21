#!/usr/bin/python3

import shared
from lib import results, oscap

new = oscap.global_ds()

with shared.get_old_datastream() as old_xml:
    old = oscap.Datastream(old_xml)

    common_profiles = set(new.profiles).intersection(old.profiles)

    for profile in sorted(common_profiles):
        old_title = old.profiles[profile].title
        new_title = new.profiles[profile].title
        if old_title != new_title:
            results.report('fail', f'{profile}/-{old_title}')
            results.report('fail', f'{profile}/+{new_title}')

results.report_and_exit()

#!/usr/bin/python3

from lib import util, results, oscap

new = oscap.global_ds()

with util.get_old_datastream() as old_xml:
    old = oscap.Datastream(old_xml)

    common_profiles = set(new.profiles).intersection(old.profiles)

    for profile in sorted(common_profiles):
        # [ ('+', 'some_var', 'value') , ('-', 'another_var', 'value') , ... ]
        added_removed = []

        old_vars = old.profiles[profile].values
        new_vars = new.profiles[profile].values
        for var in old_vars - new_vars:
            name, value = var
            added_removed.append(('-', name, value))
        for var in new_vars - old_vars:
            name, value = var
            added_removed.append(('+', name, value))

        for sign, name, value in sorted(added_removed, key=lambda x: x[1]):
            results.report('fail', f'{profile}/{sign}{name}={value}')

results.report_and_exit()

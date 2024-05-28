#!/usr/bin/python3

from lib import util, results, oscap

new = oscap.global_ds()

with util.get_old_datastream() as old_xml:
    old = oscap.Datastream(old_xml)

    for rule in sorted(set(old.rules) - set(new.rules)):
        results.report('fail', rule)

results.report_and_exit()

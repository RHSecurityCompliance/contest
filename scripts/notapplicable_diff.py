#!/usr/bin/python3

"""
This is a standalone script for comparing a full set of results from provided
results.json.gz files and finding any rules that existed previously as
applicable, but a new version (of results.json.gz) revealed them to be freshly
notapplicable.

This is critical for finding real issues that might be hidden by applicability
changes (rule worked before, is accidentally hidden as notapplicable now).
"""

import re
import sys
import gzip
import json
import argparse
import textwrap


def extract_results(filepath, args):
    """
    Extract results line-by-line from results.json.gz.

    Yields: ((platform_string, test_name), (status, note)) tuples
    where platform_string is like "9.0@x86_64" or "9.0"
    """
    with gzip.open(filepath, 'rt') as stream:
        for line in stream:
            json_line = json.loads(line)
            platform, status, test, subtest, _files, note = json_line

            # assemble full test name
            name = f'{test}/{subtest}' if subtest else test

            # only /hardening results (tmt result reported for each rule)
            if not name.startswith('/hardening/'):
                continue

            # extract RHEL version and arch from platform string
            if '@' in platform:
                rhel = re.sub(r'@.*', '', platform)
                arch = re.sub(r'.*@', '', platform)
            else:
                rhel = platform
                arch = 'x86_64'

            # apply filters
            if args.ignore_rhel and any(x == rhel for x in args.ignore_rhel):
                continue
            if args.ignore_arch and any(x == arch for x in args.ignore_arch):
                continue
            if args.ignore_test and any(re.match(x, name) for x in args.ignore_test):
                continue

            # retain compatibility with str(empty note) being '', not 'None'
            if note is None:
                note = ''

            # Use (platform, test_name) as the key for quick lookup
            key = (platform, name)
            yield (key, (status, note))


if __name__ == '__main__':
    epilog = textwrap.dedent(r"""
        This tool parses two results.json.gz files (stabilization CI artifacts
        produced by ATEX), extracting any 'notapplicable' results, diffing them
        against each other.

        The tool focuses on identifying rules that became notapplicable
        or became applicable, while ignoring newly added or removed
        tests that may just be due to different RHEL versions being tested.

        Mount option rules for host-os partitions (home, opt, srv, var, tmp, …)
        are reported in a separate section because partition layout is not
        controlled by the hardening content.

        Examples:
          # Ignore results from RHEL 9.8 and 10.2 (e.g., versions not tested in old run)
          %(prog)s --ignore-rhel 9.8 --ignore-rhel 10.2 old.json.gz new.json.gz

          # Ignore specific architecture
          %(prog)s --ignore-arch s390x old.json.gz new.json.gz
    """)
    parser = argparse.ArgumentParser(
        epilog=epilog,
        formatter_class=argparse.RawTextHelpFormatter,
        usage=f'{sys.argv[0]} [options] <old_results> <new_results>',
    )
    parser.add_argument('--ignore-arch', metavar='ARCH', action='append',
                        help="Skip any results from this architecture")
    parser.add_argument('--ignore-rhel', metavar='RHEL', action='append',
                        help="Skip any results from RHEL version")
    parser.add_argument('--ignore-test', metavar='REGEX', action='append',
                        help="Skip any results with test name matching a TMT regex")
    parser.add_argument('old_results')
    parser.add_argument('new_results')

    args = parser.parse_args()

    # Read OLD results into a dict for quick lookup
    old = dict(extract_results(args.old_results, args))

    # Iterate over NEW results and compare with OLD
    new = dict(extract_results(args.new_results, args))

    # -------------------------------------------------------------------------
    # Check platform coverage differences
    # -------------------------------------------------------------------------

    def extract_platforms(result_dict):
        """Extract unique platforms (RHEL version + arch) from results."""
        platforms = set()
        for platform, _test_name in result_dict.keys():
            platforms.add(platform)
        return platforms

    old_platforms = extract_platforms(old)
    new_platforms = extract_platforms(new)

    only_in_old = old_platforms - new_platforms
    only_in_new = new_platforms - old_platforms
    in_both = old_platforms & new_platforms

    if only_in_old or only_in_new:
        print("WARNING: Platform coverage differs between result files")
        print("=" * 80)

        if only_in_old:
            print(f"\nPlatforms only in OLD results ({len(only_in_old)}):")
            for platform in sorted(only_in_old):
                print(f"  - {platform}")
            print("  (these platforms will be ignored in the comparison)")

        if only_in_new:
            print(f"\nPlatforms only in NEW results ({len(only_in_new)}):")
            for platform in sorted(only_in_new):
                print(f"  + {platform}")
            print("  (these platforms will be ignored in the comparison)")

        print(f"\n{'=' * 80}\n")

    # we don't control partitions on the host OS — tracked separately
    # https://github.com/RHSecurityCompliance/contest/blob/16629441ef3489866f9c1827226d9b66309184a6/conf/waivers/infrastructure#L10
    _PARTITION_RULE_RE = re.compile(
        r'/hardening/host-os/.+/mount_option_'
        r'(home|opt|srv|var|var_log|var_log_audit|tmp)_'
        r'(noexec|nosuid|nodev|usrquota|grpquota)'
    )

    # -------------------------------------------------------------------------
    # Group by rule basename (last component of test path)
    # became_notapplicable[rule_basename] = [(platform, full_test_name, old_status, old_note), ...]
    became_notapplicable = {}
    became_applicable = {}
    partition_became_notapplicable = {}
    partition_became_applicable = {}

    # Check all tests that exist in both old and new
    for key in new.keys():
        if key not in old:
            continue

        platform, test_name = key
        old_status, old_note = old[key]
        new_status, new_note = new[key]

        old_is_notapplicable = (old_status == 'skip' and old_note == 'notapplicable')
        new_is_notapplicable = (new_status == 'skip' and new_note == 'notapplicable')

        # Extract rule basename (last component of path)
        rule_basename = test_name.split('/')[-1]

        is_partition = bool(_PARTITION_RULE_RE.search(test_name))

        # Rule became notapplicable (regression)
        if new_is_notapplicable and not old_is_notapplicable:
            bucket = partition_became_notapplicable if is_partition else became_notapplicable
            if rule_basename not in bucket:
                bucket[rule_basename] = []
            bucket[rule_basename].append((platform, test_name, old_status, old_note))

        # Rule became applicable (improvement)
        elif old_is_notapplicable and not new_is_notapplicable:
            bucket = partition_became_applicable if is_partition else became_applicable
            if rule_basename not in bucket:
                bucket[rule_basename] = []
            bucket[rule_basename].append((platform, test_name, new_status, new_note))

    # -------------------------------------------------------------------------
    # Report findings
    # -------------------------------------------------------------------------

    def print_section(title, rules_dict, empty_msg):
        if not rules_dict:
            print(f"{empty_msg}\n")
            return
        print(f"{title}:")
        print("=" * 80)
        total_instances = 0
        for rule_basename in sorted(rules_dict.keys()):
            platforms_list = rules_dict[rule_basename]
            total_instances += len(platforms_list)

            print(f"\nRule: {rule_basename}")
            print(f"  Affected platforms ({len(platforms_list)}):")

            by_rhel = {}
            for platform, test_name, *_ in platforms_list:
                rhel, arch = platform.split('@') if '@' in platform else (platform, 'x86_64')
                by_rhel.setdefault(rhel, []).append((arch, test_name))

            for rhel in sorted(by_rhel.keys()):
                archs = sorted(set(arch for arch, _ in by_rhel[rhel]))
                print(f"    RHEL {rhel}: {', '.join(archs)}")

            unique_paths = sorted(set(test_name for _, test_name, *_ in platforms_list))
            if len(unique_paths) > 1:
                print(f"  Test paths:")
                for path in unique_paths:
                    print(f"    {path}")

        print(f"\n{'=' * 80}")
        print(f"Total: {len(rules_dict)} unique rules across {total_instances} platform/test combinations\n")

    print_section("Rules that became NOTAPPLICABLE", became_notapplicable,
                  "No rules became notapplicable (no regressions found)")
    print_section("Rules that became APPLICABLE", became_applicable,
                  "No rules became applicable")

    if partition_became_notapplicable or partition_became_applicable:
        print("NOTE: Partition mount-option rules (host-OS layout not controlled by hardening content)")
        print("=" * 80)
        print_section("  Partition rules that became NOTAPPLICABLE", partition_became_notapplicable,
                      "  No partition rules became notapplicable")
        print_section("  Partition rules that became APPLICABLE", partition_became_applicable,
                      "  No partition rules became applicable")

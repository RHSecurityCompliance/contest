import sys
import re
import enum
import contextlib
import collections
import types
import xml.etree.ElementTree as ET
from pathlib import Path

from lib import util, results


class Datastream:
    FixType = enum.Flag('FixType', ['bash', 'ansible'])

    def __init__(self, xml_file=None):
        # extracted datastream metadata
        #   self.profiles = {
        #     'ospp': namespace(
        #       .title = 'Some text',
        #       .rules = set( 'audit_delete_success' , 'service_firewalld_enabled' , ...),
        #       .values = set( ('var_rekey_limit_size','1G') , ...),
        #     ),
        #   }
        #   self.rules = {
        #     'configure_crypto_policy': namespace(
        #       .fixes = FixType.bash | FixType.ansible,
        #     ),
        #     'account_password_selinux_faillock_dir': namespace(
        #       .fixes = FixType.bash,
        #     ),
        #   }
        def make_profile():
            return types.SimpleNamespace(title=None, rules=set(), values=set())
        self.profiles = collections.defaultdict(make_profile)
        def make_rule():
            return types.SimpleNamespace(fixes=self.FixType(0))
        self.rules = collections.defaultdict(make_rule)
        if xml_file:
            self.parse_xml(xml_file)

    def parse_xml(self, xml_file):
        # parse input XML datastream in 10KB binary chunks (arbitrary
        # reasonable value), pass them to the ElementTree parser, which
        # returns element start/end events
        parser = ET.XMLPullParser(events=['start', 'end'])
        # this is a stack of parsed XML elements - it gets filled up as we
        # recurse deeper into the XML element tree
        stack = []
        with open(xml_file, 'rb') as f:
            while True:
                chunk = f.read(10000)
                if not chunk:
                    break
                parser.feed(chunk)

                for event, elem in parser.read_events():
                    if event == 'start':
                        stack.append(elem)
                    else:
                        # optimize a bit - filter out elements too shallow for anything below
                        if len(stack) < 4:
                            stack.pop()
                            continue

                        # the logic below tries to match the last one/two elements
                        # in the stack, to hopefully limit false positive matches
                        # elsewhere in the XML tree (if only element name was used)
                        # - note that this runs on the 'end' parser event, so child
                        #   elements will appear before parent ones

                        # transform stack elements into namespace-free tag names, for
                        # easier tag name matching
                        frames = [elem.tag.partition('}')[2] or elem.tag for elem in stack]

                        # profiles
                        if frames[-1] == 'Profile':
                            profile = stack[-1].get('id')
                            # TODO: use str.removeprefix after RHEL-7
                            profile = re.sub('^xccdf_org.ssgproject.content_profile_', '', profile)
                            self.profiles[profile]  # let defaultdict fill in the values

                        # profile contents
                        elif frames[-2] == 'Profile':
                            profile = stack[-2].get('id')
                            # TODO: use str.removeprefix after RHEL-7
                            profile = re.sub('^xccdf_org.ssgproject.content_profile_', '', profile)
                            # title
                            if frames[-1] == 'title':
                                text = stack[-1].text
                                self.profiles[profile].title = text
                            # rule selection
                            elif frames[-1] == 'select':
                                if elem.get('selected') == 'true':
                                    rule = stack[-1].get('idref')
                                    # TODO: use str.removeprefix after RHEL-7
                                    rule = re.sub('^xccdf_org.ssgproject.content_rule_', '', rule)
                                    self.profiles[profile].rules.add(rule)
                            # variable refinement
                            elif frames[-1] == 'refine-value':
                                name = stack[-1].get('idref')
                                # TODO: use str.removeprefix after RHEL-7
                                name = re.sub('^xccdf_org.ssgproject.content_value_', '', name)
                                contents = stack[-1].get('selector')
                                self.profiles[profile].values.add((name, contents))

                        # rules
                        elif frames[-1] == 'Rule':
                            rule_id = stack[-1].get('id')
                            # TODO: use str.removeprefix after RHEL-7
                            rule_id = re.sub('^xccdf_org.ssgproject.content_rule_', '', rule_id)
                            self.rules[rule]  # let defaultdict fill in the values

                        # fixes / remediations
                        elif frames[-2:] == ['Rule', 'fix']:
                            system = stack[-1].get('system')
                            if system == 'urn:xccdf:fix:script:sh':
                                fix_type = self.FixType.bash
                            elif system == 'urn:xccdf:fix:script:ansible':
                                fix_type = self.FixType.ansible
                            else:
                                fix_type = None
                            if fix_type:
                                for_rule = stack[-1].get('id')
                                self.rules[for_rule].fixes |= fix_type
                        stack.pop()

    def has_remediation(self, rule):
        """
        Return True if 'rule' has bash remediation, False otherwise.
        """
        if rule not in self.rules:
            return False
        # TODO: come up with a different way of handling "no remediation" cases,
        #       retain the current "has no *bash* remediation" behavior for now
        return bool(self.rules[rule].fixes & self.FixType.bash)

    def get_all_profiles_rules(self):
        """
        Return a deduplicated unified set of all rules from all profiles.
        """
        return set(rule for profile in self.profiles.values() for rule in profile.rules)


# "global" datastream singleton, based on a xml file location decided by
# util/content.py, useful for the vast majority of tests that work with only
# one datastream, as provided by an installed RPM, or via a user-specified
# environment variable
# - any tests that work with .xml files directly (and need access to profiles
#   or rules inside them) should instantiate class Datastream() themselves
_cached_global_ds = None


def global_ds():
    global _cached_global_ds
    if _cached_global_ds is None:
        _cached_global_ds = Datastream(util.get_datastream())
    return _cached_global_ds


def rule_from_verbose(line):
    """
    Get (rulename, status) from an oscap info verbose output line.

    Return None if the input line is not a valid oscap verbose result line.
    """
    match = re.match(r'^xccdf_org.ssgproject.content_rule_(.+):([a-z]+)$', line)
    if match:
        return (match.group(1), match.group(2))
    else:
        return None


def report_from_verbose(lines):
    """
    Report results from oscap output.

    Note that this expects 'oscap xccdf eval' to be run:
      - with --progress
      - with stdout parsed into lines, fed to this function
      - with stderr discarded or left on the console
    """
    total = 0

    for line in lines:
        # oscap xccdf eval --progress rule name and status
        match = rule_from_verbose(line)
        if match:
            rule, status = match
        else:
            sys.stdout.write(f'{line}\n')
            sys.stdout.flush()
            continue

        total += 1
        note = None

        if status in ['pass', 'error']:
            pass
        elif status == 'fail':
            if not global_ds().has_remediation(rule):
                note = 'no remediation'
                status = 'warn'
        elif status in ['notapplicable', 'notchecked', 'notselected', 'informational']:
            note = status
            status = 'info'
        else:
            note = status
            status = 'error'

        results.report(status, rule, note)

    if total == 0:
        raise RuntimeError("oscap returned no results")

    util.log(f"all done: {total} total results")


@contextlib.contextmanager
def unselect_rules(orig_ds, new_ds, rules):
    """
    Given
    - a source XML file path as 'orig_ds',
    - a destination XML file path as 'new_ds',
    - an iterable of rules (partial or full rule names),
    copy the source datastream to the destination one, disabling the
    specified rules.
    """
    prefix = 'xccdf_org.ssgproject.content_rule_'
    rules = (x if x.startswith(prefix) else prefix + x for x in rules)

    exprs = set()
    for rule in rules:
        exprs.add(re.compile(fr'<.*Rule.*id="{rule}'))
        exprs.add(re.compile(fr'<.*select.*idref="{rule}'))

    new_ds = Path(new_ds)
    # remove a possible existing/old file
    if new_ds.exists():
        new_ds.unlink()

    util.log(f"reading {orig_ds}, writing to {new_ds}")
    with open(orig_ds) as orig_ds_f:
        with open(new_ds, 'w') as new_ds_f:
            for line in orig_ds_f:
                if any(x.search(line) for x in exprs):
                    line = line.replace('selected="true"', 'selected="false"')
                    util.log(f"unselected {line.strip()}")
                new_ds_f.write(line)

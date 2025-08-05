import sys
import re
import enum
import contextlib
import collections
import types
import xml.etree.ElementTree as ET
from pathlib import Path

from lib import util, results


def parse_xml(path):
    """
    Parse an XML file, yielding tuples of
        (frames, elements)
    where each is an ordered list of namespace-free tag names ('frames') and the
    actual ElementTree objects ('elements') as it appears during a top-down
    recursive traversal.
    The yielded tuples are returned as child-first (as the parser *exits* the
    elements) in order to return complete Element objects.

    Ie. for a <Tag1> containing <Tag2>, this would yield:

        (['Tag1', 'Tag2'], [Element <Tag1> at 0x...>, <Element 'Tag2' at 0x...>])
        (['Tag1'], [Element <Tag1> at 0x...>])

    The intention is for the caller to match a specific part of the XML file
    by comparing the last N members of the frames list, and/or the element list,
    extracting further details from the last element.
    """
    # parse input XML tream in 10KB binary chunks (arbitrary reasonable value),
    # pass them to ElementTree parser, which returns element start/end events
    parser = ET.XMLPullParser(events=['start', 'end'])
    frames = []
    elements = []
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(10000)
            if not chunk:
                break
            parser.feed(chunk)
            for event, elem in parser.read_events():
                if event == 'start':
                    frames.append(elem.tag.partition('}')[2] or elem.tag)
                    elements.append(elem)
                else:
                    yield (frames, elements)
                    frames.pop()
                    elements.pop()


class Datastream:
    FixType = enum.Flag('FixType', ['bash', 'ansible'])

    def __init__(self, xml_file):
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
        #   self.path = Path(file_the_datastream_was_parsed_from)
        def make_profile():
            return types.SimpleNamespace(title=None, rules=set(), values=set())

        self.profiles = collections.defaultdict(make_profile)

        def make_rule():
            return types.SimpleNamespace(fixes=self.FixType(0))

        self.rules = collections.defaultdict(make_rule)
        self._parse_datastream_xml(xml_file)
        self.path = Path(xml_file)

    def _parse_datastream_xml(self, xml_file):
        for frames, elements in parse_xml(xml_file):
            # optimize a bit - filter out elements too shallow for anything below
            if len(frames) < 4:
                continue

            # the logic below tries to match the last one/two elements
            # in the stack, to hopefully limit false positive matches
            # elsewhere in the XML tree (if only element name was used)

            # profiles
            if frames[-1] == 'Profile':
                profile = elements[-1].get('id')
                profile = profile.removeprefix('xccdf_org.ssgproject.content_profile_')
                self.profiles[profile]  # let defaultdict fill in the values

            # profile contents
            elif frames[-2] == 'Profile':
                profile = elements[-2].get('id')
                profile = profile.removeprefix('xccdf_org.ssgproject.content_profile_')
                # title
                if frames[-1] == 'title':
                    text = elements[-1].text
                    self.profiles[profile].title = text
                # rule selection
                elif frames[-1] == 'select':
                    if elements[-1].get('selected') == 'true':
                        rule = elements[-1].get('idref')
                        rule = rule.removeprefix('xccdf_org.ssgproject.content_rule_')
                        self.profiles[profile].rules.add(rule)
                # variable refinement
                elif frames[-1] == 'refine-value':
                    name = elements[-1].get('idref')
                    name = name.removeprefix('xccdf_org.ssgproject.content_value_')
                    contents = elements[-1].get('selector')
                    self.profiles[profile].values.add((name, contents))

            # rules
            elif frames[-1] == 'Rule':
                rule_id = elements[-1].get('id')
                rule_id = rule_id.removeprefix('xccdf_org.ssgproject.content_rule_')
                self.rules[rule_id]  # let defaultdict fill in the values

            # fixes / remediations
            elif frames[-2:] == ['Rule', 'fix']:
                system = elements[-1].get('system')
                if system == 'urn:xccdf:fix:script:sh':
                    fix_type = self.FixType.bash
                elif system == 'urn:xccdf:fix:script:ansible':
                    fix_type = self.FixType.ansible
                else:
                    fix_type = None
                if fix_type:
                    for_rule = elements[-1].get('id')
                    self.rules[for_rule].fixes |= fix_type

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
        return {rule for profile in self.profiles.values() for rule in profile.rules}


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


def rules_from_verbose(lines):
    """
    Yield (rulename, status) from oscap info verbose output lines.
    """
    for line in lines:
        # oscap xccdf eval --progress rule name and status
        match = rule_from_verbose(line)
        if match:
            yield match
        else:
            # print out unrelated lines
            sys.stdout.write(f'{line}\n')
            sys.stdout.flush()


def report_from_verbose(lines):
    """
    Report results from oscap output.

    Note that this expects 'oscap xccdf eval' to be run:
      - with --progress
      - with stdout parsed into lines, fed to this function
      - with stderr discarded or left on the console
    """
    total = 0
    total_nonresults = 0

    for rule, status in rules_from_verbose(lines):
        total += 1
        note = None

        if status in ['pass', 'error']:
            pass
        elif status == 'fail':
            if not global_ds().has_remediation(rule):
                note = 'no remediation'
                status = 'warn'
        elif status in ['notapplicable', 'notchecked', 'notselected', 'informational']:
            total_nonresults += 1
            note = status
            status = 'skip'
        else:
            note = status
            status = 'error'

        results.report(status, rule, note)

    if total == 0:
        raise RuntimeError("oscap returned no results")
    if total == total_nonresults:
        raise RuntimeError("oscap didn't return any pass/fail/error results")

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

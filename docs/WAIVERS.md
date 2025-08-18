# Waiving known failures

## Directory structure

The files inside the [waivers directory](../conf/waivers) are read in
an alphanumeric order, including (sub)directories and any files inside them,
forming a contiguous list of `<section>`s (as described below) from their
contents.

By convention, file names inside the waivers directory have specific meaning:

- `unknown` - these are for waiving not-yet-known failures that we simply
  don't want failing in daily runs while somebody investigates them
- `long-term` - these are for investigated issues, which typically have
  bugs or issues filed, and are waiting for a fix
- `permanent` - these are never expected to be fixed, as they are a result
  of the test infrastructure specifics, or other test or technology
  limitations
  - note that they may still disappear over time, ie. by dropping support
    for an old OS release, which had the limitation

## Sections

The files inside the waivers directory use a custom file format to specify
when a failure is expected.  
This format consists of so-called "sections", optionally separated by any
number of empty lines. Any lines beginning with `#` are skipped.

```
<section>

# some comment
<section>

...
```

Each section consists of two parts:

- a list of result names, as regular expressions
- a whitespace-indented block with a python code expression

```python
/some/result/name
/some/other/.*/result
    True if some_condition else \
        True if some_other_condition else False

/some/more/test/results
    rhel < 9
```

## Regular expressions

The regexps use a pythonic syntax, and are matched using `re.fullmatch()`,
meaning they always match the full result name, not a substring.

This is to easily and naturally support specifying result names as-is,
without any regular expression characters.

Ie. this behaves as expected, always matching only on the full name:

```
/some/result/name
```

If you need to match only a substring (prefix), emulating `re.match()`,
use wildcards:

```
/some/result/name.*
```

Or `re.search()` behavior using:

```
.*/some/result/name.*
```

## Python expressions

The python code block must always be one expression, not a freeform python
module code.

The expression has these globals available:

- `status` - the original result status (`pass`, `fail`, `error`, etc.)
- `name` - the result (test) name, empty string if unspecified
- `note` - an optional note associated with the result, or empty string
- `arch` - platform (architecture) name (`x86_64`, `ppc64le`, etc.)
- `rhel` - an object capable of RHEL version comparison, see
  [versions.rhel](../lib/versions.py)
- `env` - environment variable retrieval function, same as `os.environ.get()`
- `no_remediation` - function which takes remediation (fix) type(s) as an argument,
  returns `bool` whether the rule extracted from the test `name` (see `match_result()`
  function in [lib/waive.py](../lib/waive.py)) has no remediation(s) of the given remediation
  type(s) in the tested datastream (under `<fix system="...">`)
- `fix` - `oscap.FixType` enum, defined in [lib/oscap.py](../lib/oscap.py)
- `Match` - a class for complex waive results, able to contain both a boolean
  expression as well as additional parameters

The version comparison objects also support a boolean evaluation, with
`bool(rhel)` returning `False` if not running on RHEL or CentOS.

```python
/some/result/name
    (rhel < 7.9 and 'some thing' in note) or \
    (rhel < 8.4 and arch == 'x86_64')

/some/other/result
    rhel == 8 and 'some thing' in note and env('INFRA') == 'jenkins'
```

The `no_remediation` function allows to waive rule results which don't
have the respective remediation type in the tested datastream. Currently,
contest supports waiving of the following remediation (fix) types:
* `fix.bash` - `urn:xccdf:fix:script:sh`
* `fix.ansible` - `urn:xccdf:fix:script:ansible`
* `fix.anaconda` - `urn:redhat:anaconda:pre`
* `fix.kickstart` - `urn:xccdf:fix:script:kickstart`
* `fix.blueprint` - `urn:redhat:osbuild:blueprint`
* `fix.bootc` - `urn:xccdf:fix:script:bootc`

For example, to waive `/hardening/kickstart` rule test results which don't
have `bash` nor `kickstart` remediation (fix) type in the datastream:
```python
/hardening/kickstart/.+
    Match(no_remediation(fix.bash | fix.kickstart), note="no bash nor kickstart remediation")
```
Results with the `name` like `/hardening/kickstart/stig/configure_crypto_policy`
would match and python expression would be evaluated. First, the rule name is
extracted from the `name` (`configure_crypto_policy`) and then if the rule doesn't
have `bash` nor `kickstart` remediation in the tested datastream it will be waived
with the specified note `no bash nor kickstart remediation`.

## Collecting a list of sections

Sections (as defined above) are gathered from multiple waiver files
in alphanumerical order, and - within each file - from the top.

This creates a one big unified sequential ordered list of sections
that is later used for waiving.

## How a result is waived

Before a result (e.g. rule result or overall test result) is reported,
the waiving logic looks at the status (`pass`, `fail`, etc.).

If the status is `info`, `skip` or `warn`, no further processing is done,
and the result remains intact.
All other statuses continue below.

The waiving logic then goes through the big list of sections (gathered
above), **from beginning to end**, and tries to match the test name
contained within the result, against all regexps in each section.

For example, a test name of `/some/result/name`, when evaluated against

```
/different/name.*
    rhel >= 8

/some/unrelated/string
/some/.+/name
/something/else
    rhel >= 8
```

would match the second section, and its `/some/.+/name` regexp.

**If no section matches on a regexp, no further processing is done,
and the result remains intact.**

When a section is matched on regexp, its python expression is evaluated.
In our example, `/some/result/name` matched `/some/.+/name` regex. The
python expression to be evaluated for this section is `rhel >= 8`.
If that expression returns `False`, the section is skipped, and result
remains intact for now. Waiving continues with further sections (in the
big unified list of sections) to look for next matching regex.

**If no section matches on both a regexp AND python expression returning
True, no further processing is done, the result remains intact.**

When the result matches on both regexp + python expression of one section,
the result is subject to waiving, and **no further sections are evaluated
for that result**.

In such a case, the waiving logic decides on reported status:

- `fail` is changed to `warn`, and "waived fail" is added to `note`
- `error` is changed to `warn`, and "waived error" is added to `note`

By default, `pass` remains unchanged, however if a waiver returns a `Match()`
object with `strict=True` passed, such as in `Match(rhel >= 8, strict=True)`
or if the `CONTEST_STRICT_WAIVERS` environment variable is set, this adds
an additional rule:

- `pass` is changed to `fail`, and "expected fail/error, got pass" is added
  to `note`

And that's it.

---

Notice that `strict=True` **does not** impact section processing, it only
decides what to do with `pass` once a section (regexp + python) has matched.

Notice also that unused sections don't cause any errors - a section that either

- never matched on regexp + python expression, or
- was never attempted to match because all results were always caught by
  earlier sections

will simply remain dormant and unused, without any error.  
(This is due to the inherent difficulty of figuring out whether a section is
*really* unused across many architectures, OS versions, etc.)

Finally, notice that if a result doesn't match any section, it "falls through"
the waiving logic:

- `fail` remains a `fail`
- `error` remains an `error`
- `pass` remains a `pass`

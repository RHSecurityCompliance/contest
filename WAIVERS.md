# Waiving known failures

## Custom file format

The [waivers file](conf/waivers) uses a custom file format to specify when
a failure is expected.  
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
    rhel < 9 and oscap < '1.3.6'
```

When a new failing result is to be reported, the sections are evaluated
sequentially, in order, **from the top**.

Within each section:  
If at least one of the consecutive regular expressions matches the result name,
the python expression is evaluated.  
If that expression also returns `True`, the result is considered waived and
the traversal stops for that one result (no further sections are tried).

If either the regular expressions don't match, or the python expression returns
False, the section is skipped and a next one is considered.

If none of the sections match, no waiving happens and the result remains
unchanged.

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

## Not just a `fail`

The waiving logic is actually evaluated for all of `pass`, `fail` and `error`.
The `pass` is there to catch any waive matches that suddenly started `pass`-ing,
and the `error` allows us to waive some infrastructure `error`s as well.

The waiving file format above therefore serves as a generic "matching logic",
and it's up to the library code to interpret what a match means.

- no match = no change
- match + pass = fail (unexpected pass)
- match + fail = warn (waived fail)
- match + error = warn (waived error)

## Matching and globals

The python code block must always be one expression, not a freeform python
module code.

The expression has these globals available:

- `status` - the original result status (`pass`, `fail`, `error`, etc.)
- `name` - the result (test) name, empty string if unspecified
- `note` - an optional note associated with the result, or empty string
- `arch` - platform (architecture) name (`x86_64`, `ppc64le`, etc.)
- `rhel` - an object capable of RHEL version comparison, see
  [versions.rhel](lib/versions.py)
- `oscap` - an object capable of `openscap-scanner` RPM version comparisons,
  see [versions.oscap](lib/versions.py)
- `env` - environment variable retrieval function, same as `os.environ.get()`
- `Match` - a class for complex waive results (see below)

The version comparison objects also support a boolean evaluation, with
`bool(rhel)` returning `False` if not running on RHEL, and ie. `bool(oscap)`
returning `False` if the RPM is not installed.

```python
/some/result/name
    (rhel < 7.9 and 'some thing' in note) or \
    (rhel < 8.4 and oscap < '0.1.66')

/some/other/result
    rhel == 8 and 'some thing' in note and env('INFRA') == 'jenkins'
```

### Expecting both `pass` and `fail`/`error`

Sometimes, failures or errors are not reliable and happen only occassionally.
This means a waive section might be throwing a lot of "unexpected pass" failures
and be rendered useless.

To fix this, pass `sometimes=True` to `Match()`, which tells the waiving code
to do nothing if there's a match for a `pass` status.

```python
/some/result/name
    Match(rhel >= 8, sometimes=True)
```

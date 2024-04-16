# Test Categories

This is not meant to be an exhaustive list, but it should hopefully shed some
light on how we categorize tests.

## `/hardening`

These specifically

1. harden the OS installation via some means (OpenSCAP, Ansible, etc.)
1. reboot
1. (re-harden + second reboot in the case of OpenSCAP, a.k.a. "double
   remediation")
1. scan the OS via `oscap xccdf eval`

All tests in this category report scanned rules as (sub)results, meaning
the output of each test is ie.

```
pass  /hardening/oscap/some_profile/some_rule_1
fail  /hardening/oscap/some_profile/some_rule_2
pass  /hardening/oscap/some_profile/some_rule_3
pass  /hardening/oscap/some_profile/some_rule_4
fail  /hardening/oscap/some_profile
```

with the last entry being for the test (code) itself, summarizing all its
(sub)results under one status.

Any logs (from remediation or scanning) are attached to the last result.

## `/scanning`

These are any other non-`/hardening` tests involving `oscap` (or other kinds of)
OS scanning.

Note that some hardening-like tests may exist here, ie. DISA alignment testing,
because these tests don't follow the result reporting structure of `/hardening`,
they instead report alignment mismatches.

## `/per-rule`

These are wrappers for Automatus-style content unit tests.

In order to run in parallel (and not take forever), they have been split into
numerical slices,

```
/per-rule/1
/per-rule/2
...
```

There is also a singular

```
/per-rule/from-env
```

that can be parametrized by the user to run only tests for user-specified rules.


## `/static-checks`

These are various miscellaneous "small" checks that don't need complex runtime
environment. They don't modify the host OS (beyond installing extra RPMs),
they don't install virtual machines.

These are things like `grep`-ing for specific strings (not) present in the built
content, syntax-checking Ansible playbooks, or verifying HTTP URLs.

# Test tags

These are some of the commonly-used tags amongst tests.

Note that we use tags to indicate properties of tests, not to categorize them
(think: "needs virtualization", not: "runs during release testing").

## `needs-param`

This indicates a test that is used as a "tool" in automation-assisted use
cases. It should not run automatically in regular "all tests" runs, as it
requires the user to give it input via environment variables (parameters).

## `always-fails`

This is a test that uses the `fail` status to indicate some unwanted findings,
expecting the user to review the list manually. These `fail`s should not be
waived automatically as they are specific to the configuration the user
requested.

A test like this is another form of a "tool" and should not be run regularly
in use cases that expect `pass` to be the norm and `fail` to be a regression.

## `broken`

This is a perfectly valid working test, but the functionality it tests is
either completely broken, or under very active development, creating interface
incompatibilities, such as config directive changes, and frequently breaking
the test.

Despite this, we don't want to disable the test outright, as it is useful for
debugging and stabilizing the tested functionality via manual use.

However a test like this should not be run by automation, it is not useful
for preventing regressions.

## `destructive`

A destructive tests modifies the OS it runs on to the point where it is
unusable for further testing, typically by hardening it.

A test that just installs extra RPMs from the package manager, or enables
extra services, is not considered destructive.

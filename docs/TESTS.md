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

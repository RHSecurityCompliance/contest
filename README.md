# Content Testing (`contest`)

This is a repository of publicly-available tests used for testing
[ComplianceAsCode/content](https://github.com/ComplianceAsCode/content/)
on Red Hat Enterprise Linux.

## Terminology

- [FMF - Flexible Metadata Format](https://github.com/teemtee/fmf/), a test
  metadata format used by TMT
- [TMT - Test Management Tool](https://github.com/teemtee/tmt/), a framework
  and a related CLI tool for running tests, see also
  [user docs here](https://tmt.readthedocs.io/en/stable/) or
  [Under The Hood](https://tmt.readthedocs.io/en/stable/guide.html#under-the-hood)
  which explains the basic much better

- "test" is a FMF object with a `test:` in its YAML definiton, ie.
  `/hardening/oscap/stig`
  - (In this case, one directory `/hardening/oscap` defines multiple tests,
    all sharing the same source code, parametrized using environment variables
    in `main.fmf`.)

- "result" is a piece of data reported by a test, containing
  - `name` - either a test name, or a test name with something appended to it,
    ie. `/hardening/oscap/stig` or `/hardening/oscap/stig/some_rule_name/etc`
  - `status` - one of `pass`, `fail`, `info`, `warn` or `error`
  - `note` - additional freeform text details about the result
  - `log` - a list of logs associated with the result

## Parameters

- `CONTEST_VERBOSE`
  - Set to an integer value to control the verbosity of reported results.
    This applies only to sub-results (`/something` after a test name), results
    for tests themselves (as seen by TMT) are always reported.
    - `0` outputs only `fail` and `error`
    - `1` (default) is `fail`, `error` and `warn`
    - `2` or greater to output everything

- `CONTEST_WAIVERS`
  - Specify a `conf/waiver-` suffix for a waiver file name inside `conf` to be
    used for waiving results. Ie. `CONTEST_WAIVERS=upstream` to use
    `conf/waivers-upstream`. Defaults to `released`.

- `CONTEST_LEAVE_GUEST_RUNNING`
  - Set to `1` to break gurantees provided by `class Guest()`, that is make the
    context manager not honor `__exit__` by leaving running guests (VMs) behind.
  - This is useful for debugging a failing OpenSCAP rule as you get the running
    virtual environment, as it was scanned, without an extra OS startup.
  - SSH instructions will be provided on stdout (python log output).
    - Alternatively, use `virsh domifaddr contest` to get the VM's IP address
      and `ssh` into it as `root` with `contest` as password.
  - However any tests that use more than 1 VM **and** rely on a shut-down VM
    state between two context-managed blocks, will break.
    - Because the VM was left running after the first context manager block.
    - Fortunately, no such test currently exists (the use case is rare).

- `CONTEST_DATASTREAM`
  - Specify a filesystem path to a datastream XML to use for testing.

- `CONTEST_PLAYBOOK`
  - Specify a filesystem path to an Ansible YAML file to use as a playbook
    for testing.  
    A magical string of '{PROFILE}' expands to a profile name being tested.

- `CONTEST_KICKSTART`
  - Specify a filesystem path to an configuration file to use as an Anaconda
    kickstart for testing.  
    A magical string of '{PROFILE}' expands to a profile name being tested.

## Waiving failed results

In this context, "to waive" means to label a failing result as known-bad,
something we have seen before and expect to fail.

Read [WAIVERS.md](WAIVERS.md) to see where/how you can set up rules to
automatically waive failures.

## Workarounds

(TODO: Find a better place for this?)

If you need to use `lib.util.httpsrv` from a test, use a port between
8080 and 8089. Libraries (`lib`) should use a port between 8090 and 8099.
See also TODOs in [STYLE.md](STYLE.md), this is a temporary limitation.

### Virtual machines and logging in

The tests perform some hacks to allow login after hardening:

- `-oPermitRootLogin=yes` in `OPTIONS` of `/etc/sysconfig/sshd`
  - This is to bypass ssh-denied root login. Doing this seems easier than trying
    to bypass several sudo-related rule remediations that disable `NOPASSWD`
    in `/etc/sudoers` and impose other limitations.
  - Fortunately, current content doesn't check `/etc/sysconfig/sshd`, so no
    rules are failing as a result of this. :)

### Using upstream/shipped content kickstarts

These have some unfortunate metadata, such as

- hardcoded network interface names
- unnecessarily large `/var/log/audit` size
- oscap Anaconda addon configuration using `scap-security-guide`

which are removed by `translate_ssg_kickstart()` [in virt.py](lib/virt.py).

## Referencing library code

See https://rhsecuritycompliance.github.io/contest/ for online Sphinx version
of the modules present in `lib`.

## Debugging

(TODO: probably move to its own document?)

Anaconda-based remediation can be debugged on a virtual machine by issuing
`virsh domifaddr contest` (where `contest` is the default VM name) to acquire
an IP address of the guest (which gets assigned just before Anaconda launches)
and doing `ssh root@that-ip-addr` from the host running the test itself (and
hosting the VM).  
There is no password for the Anaconda environment, so this will just log you in.

## License

Unless specified otherwise, any content within this repository is distributed
under the GNU GPLv3 license, see the [COPYING.txt](COPYING.txt) file for more.

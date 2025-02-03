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

- `CONTEST_WAIVER_DIR`
  - Specify a relative path to a waiver directory containing waiver files.
    - The directory itself is traversed recursively (may contain further
      sub-directories).
  - All files and directories are read in a locale-specific sorted order,
    and their contents combined to a final list of waiver rules.
  - Files and directories starting with `.` are ignored.
  - Defaults to `conf/waivers`.

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

- `CONTEST_VERBATIM_RESULTS`
  - Set to `1` to avoid waiving known failures, leaving results exactly as
    tests reported them.
  - Useful when you want the *actual* result of ie. `/per-rule/from-env`,
    rather than the waived one.

- `CONTEST_STRICT_WAIVERS`
  - Set to `1` to force all waivers to be `strict=True`.
  - See [WAIVERS.md](docs/WAIVERS.md) for more.

- `CONTEST_CONTENT`
  - Specify a path to a content source directory (as cloned from
    [CaC/content](https://github.com/ComplianceAsCode/content/)) to be used
    for testing.
  - The content should be already built (at least for the product under test).
    If it is not, an attempt will be made to build it in-place (rather than
    in a temporary directory) so that any future tests benefit from the built
    content.
    - Note that this may fail if the content is located on a read-only path.

- `CONTEST_CONTENT_BRANCH`
  - Specify a branch name of the
    [CaC/content](https://github.com/ComplianceAsCode/content/) project.
  - This will download content from the specified branch and automatically
    pre-set `CONTEST_CONTENT` to point to it.
  - Essentially, this is like `CONTEST_CONTENT` but without you having to
    provide a cloned directory, Contest automatically clones it for you.
  - Do not specify `CONTEST_CONTENT` in combination with this option.

- `CONTEST_CONTENT_PR`
  - Specify a numerical Pull Request ID (no `#` or other letters) of the
    [CaC/content](https://github.com/ComplianceAsCode/content/) project.
  - This is like `CONTEST_CONTENT_BRANCH`, but it uses content from the
    pull request instead of a branch.
  - Do not specify `CONTEST_CONTENT` in combination with this option.

- `CONTEST_OSCAP_BRANCH`
  - Specify a branch name of the
    [OpenSCAP](https://github.com/OpenSCAP/openscap/) project.
  - This will add a Packit DNF repository (specific for the branch) to
    the target system, and upgrade `openscap-scanner`.
  - As such, `openscap-scanner` built by Packit has to have a newer NVR
    than the RPM provided by regular OS repositories.

- `CONTEST_OSCAP_PR`
  - Specify a numerical Pull Request ID (no `#` or other letters) of the
    [OpenSCAP](https://github.com/OpenSCAP/openscap/) project.
  - This works like `CONTEST_OSCAP_BRANCH`, but it upgrades to a Packit-built
    version from the pull request, instead of a branch.
  - Wait for Packit to build the RPM before running tests with this variable,
    otherwise the test run will fail.

## Included test categories

See [TESTS.md](docs/TESTS.md).

## Waiving failed results

In this context, "to waive" means to label a failing result as known-bad,
something we have seen before and expect to fail.

Read [WAIVERS.md](docs/WAIVERS.md) to see where/how you can set up rules to
automatically waive failures.

## Workarounds

(TODO: Find a better place for this?)

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

### SSH into Anaconda

Anaconda-based remediation can be debugged on a virtual machine by issuing
`virsh domifaddr contest` (where `contest` is the default VM name) to acquire
an IP address of the guest (which gets assigned just before Anaconda launches)
and doing `ssh root@that-ip-addr` from the host running the test itself (and
hosting the VM).  
There is no password for the Anaconda environment, so this will just log you in.

### SSH into installed VMs

You can use a handy script in the home directory of the VM host's user.  
Simply run:

```
./contest-sshvm [vm-name]
```

The script will find the first contest-installed VM if `vm-name` is not given,
it will check whether the VM is running (as a result of you starting it earlier
or `CONTEST_LEAVE_GUEST_RUNNING=1`) and if not, it will start it and wait for
`sshd` to start responding. It will then `ssh` you into the VM, using
pre-generated SSH keys (no passwords needed).

## License

Unless specified otherwise, any content within this repository is distributed
under the GNU GPLv3 license, see the [COPYING.txt](COPYING.txt) file for more.

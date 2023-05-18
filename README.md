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
  - Set to `1` to make Beaker/TMT report all results, incl. `pass`, `warn` and
    `info`. These are suppressed by default to avoid huge result sets.  
    This applies to sub-results (`/something` after a test name), results for
    tests themselves (as seen by TMT) are always reported.

## Testing latest upstream content

Note that as the
[relevant TMT plan says in its description](plans/upstream-copr.fmf),
this is just a convenience feature, it shouldn't be relied upon.

Normally, you would run this test suite via `tmt` as ie.

```
tmt \
    -c distro=rhel-9.2 \
    run -vvva \
        plans -n /plans/default \
        provision -h ... \
        discover -h fmf -t '/hardening/anaconda/stig$' \
        report -h html
```

and this simply uses content shipped in whatever distro you specify to
`provision`, or whatever distro is already installed if you use
`provision -h connect ...`.

To install latest available upstream content as an RPM (built cca 15 minutes
after every push/merge to the upstream content repository), simply specify
the `/plans/upstream-copr` TMT plan instead of `/plans/default`.

## Waiving failed results

In this context, "to waive" means to label a failing result as known-bad,
something we have seen before and expect to fail.

Read [WAIVES.md](WAIVES.md) to see where/how you can set up rules to
automatically waive failures.

## Workarounds

(TODO: Find a better place for this?)

### Virtual machines and logging in

The VM-using `/hardening` tests do two hacks to allow login after hardening:

- `-oPermitRootLogin=yes` in `OPTIONS` of `/etc/sysconfig/sshd`
  - This is to bypass ssh-denied root login. Doing this seems easier than trying
    to bypass several sudo-related rule remediations that disable `NOPASSWD`
    in `/etc/sudoers` and impose other limitations.
  - Fortunately, current content doesn't check `/etc/sysconfig/sshd`, so no
    rules are failing as a result of this. :)
- `chage -d 99999 root`
  - This resets the password-changed time for root, allowing us to log in again
    without actually changing the password (and going through pwquality checks).

The `chage` specifically needs a bit more context - the binary itself has some
advanced SELinux checking for `/sys/fs/selinux/access` and throws
`Permission denied` even when it actually could do the change. This is why we

- set `virt_qemu_ga_t` as a permissive domain (during OS install), allowing
  the qemu-guest-agent (ga) to run any commands without SELinux denials
- execute `setenforce 0` prior to `chage` via the guest agent, fooling `chage`
  into thinking SELinux is disabled

As a TODO, consider using `sed` to edit `/etc/shadow`, instead of `chage`,
to avoid this complex situation.

Note that we need qemu-guest-agent to execute the `chage` for us - we cannot do
it via SSH, as we get locked out the second a remediation finishes. This is fine
for `oscap`, as we can simply do `oscap xccdf eval ... ; chage ...` in the same
shell, but Ansible remediation cannot do this.  
So we need a simple side-channel that can run `chage` **after** ansible-playbook
finishes.

### Using upstream/shipped content kickstarts

These have some unfortunate metadata, such as

- hardcoded network interface names
- unnecessarily large `/var/log/audit` size
- oscap Anaconda addon configuration using `scap-security-guide`

which are removed by `translate_ssg_kickstart()` [in virt.py](lib/virt.py).

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

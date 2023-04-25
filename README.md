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

(TODO: Probably document this on a better place.)

- `CONTEST_SILENT`
  - set to `1` to verbosely report only genuine oscap rule failures
  - other results are unaffected (for now)

- `CONTEST_DATASTREAMS`
  - alternate location for `/usr/share/xml/scap/ssg/content`
- `CONTEST_PLAYBOOKS`
  - alternate location for `/usr/share/scap-security-guide/ansible`
- `CONTEST_KICKSTARTS`
  - alternate location for `/usr/share/scap-security-guide/kickstart`

## Workarounds

(TODO: Find a better place for this?)

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

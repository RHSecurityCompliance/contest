#!/usr/bin/python3

import os
import shutil
from lib import results, oscap, versions, virt, podman, util
from conf import remediation


virt.Host.setup()

_, variant, profile = util.get_test_name().rsplit('/', 2)
with_fips = os.environ.get('WITH_FIPS') == '1'
oscap_repo = os.environ.get('CONTEST_OSCAP_REPOFILE')

oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())

# note that the .wipe() is necessary here, as we are not calling any .install()
# function that would normally perform it
guest = virt.Guest()
guest.wipe()
guest.generate_ssh_keypair()

# select appropriate container image based on host OS
major = versions.rhel.major
minor = versions.rhel.minor
if versions.rhel.is_true_rhel():
    src_image = f'images.paas.redhat.com/testingfarm/rhel-bootc:{major}.{minor}'
else:
    src_image = f'quay.io/centos-bootc/centos-bootc:stream{major}'

# prepare a RpmPack with testing-specific hacks
# - copy it to CWD because podman cannot handle absolute paths (or relative ones
#   going above CWD) as source for COPY or RUN --mount
pack = util.RpmPack()
if oscap_repo:
    pack.add_file(oscap_repo)
pack.add_sshd_late_start()
with pack.build() as pack_binrpm:
    shutil.copy(pack_binrpm, 'contest-pack.rpm')

# prepare a Container file for making a hardened image
cfile = podman.Containerfile()
cfile += util.dedent(fr'''
    FROM {src_image}
    # install testing-specific RpmPack
    COPY contest-pack.rpm /root/.
    RUN dnf -y install /root/contest-pack.rpm && rm -f /root/contest-pack.rpm
    # copy over testing-specific datastream
    COPY remediation-ds.xml /root/.
    # install and run oscap-im to harden the image
    RUN dnf -y install openscap-utils
    RUN oscap-im --profile '{profile}' \
        --results-arf /root/remediation-arf.xml /root/remediation-ds.xml
''')
cfile.add_ssh_pubkey(guest.ssh_pubkey)
cfile.write_to('Containerfile')

podman.podman('pull', src_image)
podman.podman('image', 'build', '--tag', 'contest-hardened', '.')

# we can't use standard CaC/content style partitioning scheme because the
# space distribution is different and the installer runs out of space,
# so define this explicitly here for now
# - note that Anaconda requires a separate /boot for 'ostreecontainer',
#   otherwise it crashes on RHEL-66155
partitions = [
    ('/boot', 1000),
    ('/', 18000),
]

ks = virt.Kickstart(partitions=partitions)

# install the VM, using a locally-hosted podman registry serving
# the hardened image for Anaconda's ostreecontainer
with podman.Registry(host_addr=virt.NETWORK_HOST) as registry:
    image_url = registry.push('contest-hardened')
    ks.append(f'ostreecontainer --url {image_url}')
    # Anaconda doesn't expose ostree --insecure-skip-tls-verification,
    # work around it using registries.conf
    raddr, rport = registry.get_listen_addr()
    ks.add_pre(
        fr'''echo -e '[[registry]]\nlocation = "{raddr}:{rport}"\n'''
        r'''insecure = true\n' >> /etc/containers/registries.conf''',
    )
    guest.install_basic(
        kickstart=ks,
        # Anaconda installer may itself perform cryptographic operations so
        # it also needs to run with fips=1, see
        # https://docs.fedoraproject.org/en-US/bootc/security-and-hardening/
        kernel_args=['fips=1'] if with_fips else None,
    )

# boot up and scan the VM
with guest.booted():
    # copy the original DS to the guest
    guest.copy_to(util.get_datastream(), 'scan-ds.xml')
    # scan the remediated system
    proc, lines = guest.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf scan-arf.xml scan-ds.xml',
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    guest.copy_from('report.html')
    guest.copy_from('remediation-arf.xml')
    guest.copy_from('scan-arf.xml')

tar = [
    'tar', '-cvJf', 'results-arf.tar.xz', 'remediation-arf.xml', 'scan-arf.xml',
]
util.subprocess_run(tar, check=True)

results.report_and_exit(logs=['report.html', 'results-arf.tar.xz'])

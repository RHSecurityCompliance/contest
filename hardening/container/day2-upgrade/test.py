#!/usr/bin/python3

import os
import shutil
from pathlib import Path

from lib import results, oscap, versions, virt, podman, util
from conf import remediation


virt.Host.setup()

profile = util.get_test_name().rpartition('/')[2]
oscap_repo = os.environ.get('CONTEST_OSCAP_REPOFILE')

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

with util.get_old_datastream() as old_xml:
    # prepare a Container file for making a hardened image using the old data stream
    oscap.unselect_rules(old_xml, 'remediation-old.xml', remediation.excludes())
    cfile = podman.Containerfile()
    cfile += util.dedent(fr'''
        FROM {src_image}
        # install testing-specific RpmPack
        COPY contest-pack.rpm /root/.
        RUN dnf -y install /root/contest-pack.rpm && rm -f /root/contest-pack.rpm
        # copy over testing-specific datastream
        COPY remediation-old.xml /root/
        # install and run oscap-im to harden the image
        RUN dnf -y install openscap-utils
        RUN oscap-im --profile '{profile}' \
            --results-arf /root/remediation-old-arf.xml /root/remediation-old.xml
        RUN bootc container lint
    ''')
    cfile.add_ssh_pubkey(guest.ssh_pubkey)
    cfile.write_to('Containerfile')

    podman.podman('pull', src_image)
    podman.podman('image', 'build', '--tag', 'contest-hardened-old', '.')

# prepare a Container file for making a hardened image using the new data stream
oscap.unselect_rules(util.get_datastream(), 'remediation-new-ds.xml', remediation.excludes())
cfile2 = podman.Containerfile()
cfile2 += util.dedent(fr'''
    FROM {src_image}
    # install testing-specific RpmPack
    COPY contest-pack.rpm /root/.
    RUN dnf -y install /root/contest-pack.rpm && rm -f /root/contest-pack.rpm
    # copy over testing-specific datastream
    COPY remediation-new-ds.xml /root/
    # install and run oscap-im to harden the image
    RUN dnf -y install openscap-utils
    RUN oscap-im --profile '{profile}' \
        --results-arf /root/remediation-arf.xml /root/remediation-new-ds.xml
    RUN bootc container lint
''')
cfile2.add_ssh_pubkey(guest.ssh_pubkey)
cfile2.write_to('Containerfile')
podman.podman('image', 'build', '--tag', 'contest-hardened-new', '.')

# pre-create a directory (inside GUEST_IMG_DIR) for storing the
# hardened image, built by bootc-image-builder
bootc_output_dir = Path(virt.GUEST_IMG_DIR) / 'bootc-image-builder-output'
if bootc_output_dir.exists():
    shutil.rmtree(bootc_output_dir)
bootc_output_dir.mkdir(parents=True)

# build the hardened image using a containerized builder
podman.podman(
    'container', 'run',
    '--rm',
    '--privileged',
    '--security-opt', 'label=type:unconfined_t',
    '--volume', f'{bootc_output_dir}:/output',
    '--volume', '/var/lib/containers/storage:/var/lib/containers/storage',
    'quay.io/centos-bootc/bootc-image-builder',
    # arguments for the builder itself
    'build',
    '--type', 'qcow2',
    '--local',
    # 'localhost/' prefix tells the builder to just use local image storage
    'localhost/contest-hardened-old',
)

# path inside the output dir seems to be hardcoded in bootc-image-builder
qcow2_path = bootc_output_dir / 'qcow2' / 'disk.qcow2'
guest.import_image(qcow2_path, 'qcow2')

with podman.Registry(host_addr=virt.NETWORK_HOST) as registry:
    image_url = registry.push('contest-hardened-new')
    # work around it using registries.conf
    raddr, rport = registry.get_listen_addr()
    # boot up and scan the VM
    with guest.booted():
        guest.copy_to(util.get_datastream(), 'scan-ds.xml')

        guest.ssh(
            fr'''echo -e '[[registry]]\nlocation = "{raddr}:{rport}"\n'''
            r'''insecure = true\n' >> /etc/containers/registries.conf''',
        )

        # Run "bootc switch" to switch the image to the new one
        proc, lines = guest.ssh_stream(f"bootc switch {raddr}:{rport}/contest-hardened-new")
        print("\n".join(lines))

        # reboot the VM to apply the new image
        # we can't use guest.soft_reboot() here, because we don't have a guest agent
        guest.ssh("reboot")
        virt.wait_for_ssh(guest.ipaddr, to_shutdown=True)
        guest.ipaddr = virt.wait_for_ifaddr(guest.name)
        virt.wait_for_ssh(guest.ipaddr)

        # copy the original DS to the guest
        # scan the remediated system
        proc, lines = guest.ssh_stream(
            f'oscap xccdf eval --profile {profile} --progress --report report.html'
            f' --results-arf scan-arf.xml scan-ds.xml',
        )
        oscap.report_from_verbose(lines)
        if proc.returncode not in [0,2]:
            raise RuntimeError(f"post-reboot oscap failed unexpectedly with {proc.returncode}")
        guest.copy_from('report.html')
        guest.copy_from('scan-arf.xml')

tar = [
    'tar', '-cvJf', 'results-arf.tar.xz', 'scan-arf.xml', 'report.html',
]
util.subprocess_run(tar, check=True)

results.report_and_exit(logs=['report.html', 'results-arf.tar.xz'])

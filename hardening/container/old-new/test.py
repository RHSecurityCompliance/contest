import os
import shutil
from pathlib import Path

from conf import remediation
from lib import oscap, podman, results, util, versions, virt

# prepare the host
virt.Host.setup()
podman.Host.setup()

profile = util.get_test_name().rpartition("/")[2]
oscap_repo = os.environ.get("CONTEST_OSCAP_REPOFILE")

# prepare old/new datastreams used for remediation
with util.get_old_datastream() as old_xml:
    oscap.unselect_rules(old_xml, "remediation-old-ds.xml", remediation.excludes())
oscap.unselect_rules(util.get_datastream(), "remediation-new-ds.xml", remediation.excludes())

# check whether the profile is in both old and new
if profile not in oscap.Datastream("remediation-old-ds.xml").profiles:
    results.report_and_exit("skip", "profile missing the old DS")
if profile not in oscap.Datastream("remediation-new-ds.xml").profiles:
    results.report_and_exit("skip", "profile missing the new DS")

# note that the .wipe() is necessary here, as we are not calling any .install()
# function that would normally perform it
guest = virt.Guest()
guest.wipe()
guest.generate_ssh_keypair()

# select appropriate container image based on host OS
major = versions.rhel.major
minor = versions.rhel.minor
cleanup_sh = None
if versions.rhel.is_true_rhel():
    src_image = f"images.paas.redhat.com/testingfarm/rhel-bootc:{major}.{minor}"
    cleanup_sh = Path(__file__).resolve().parent.parent / "bootc_tf_img_cleanup.sh"
    if not cleanup_sh.exists():
        cleanup_sh = None
else:
    src_image = f"quay.io/centos-bootc/centos-bootc:stream{major}"

# prepare a RpmPack with testing-specific hacks
pack = util.RpmPack()
if oscap_repo:
    pack.add_file(oscap_repo)
pack.add_sshd_late_start()
with pack.build() as pack_binrpm:
    shutil.copy(pack_binrpm, "contest-pack.rpm")


# prepare a Containerfile and build a hardened image inside 'builder'
def build_image(builder, data_stream, results_arf, dst_image):
    cfile = podman.Containerfile()
    cfile += f"FROM {src_image}"
    if cleanup_sh:
        cfile += util.dedent("""
            COPY bootc_tf_img_cleanup.sh /root/bootc_tf_img_cleanup.sh
            RUN chmod +x /root/bootc_tf_img_cleanup.sh && /root/bootc_tf_img_cleanup.sh
        """)
    cfile += util.dedent(fr"""
        # install testing-specific RpmPack
        COPY contest-pack.rpm /root/.
        RUN dnf -y install /root/contest-pack.rpm && rm -f /root/contest-pack.rpm
        # copy over testing-specific datastream
        COPY {data_stream} /root/
        # install and run oscap-im to harden the image
        RUN dnf -y install openscap-utils
        RUN oscap-im --profile '{profile}' --results-arf '{results_arf}' '/root/{data_stream}'
        # debug only: run a lint check but don't fail the build in case of any issues
        RUN bootc container lint || true
    """)
    cfile.add_ssh_pubkey(guest.ssh_pubkey)
    cfile.write_to("Containerfile")

    builder.copy_to("Containerfile", "/root/build/")
    builder.ssh("podman", "image", "build", "--tag", dst_image, "/root/build", check=True)


with podman.Registry(host_addr=virt.NETWORK_HOST, guest_addr=virt.NETWORK_GUEST) as registry:
    raddr, rport = registry.get_guest_listen_addr()
    guest_image_url = f"{raddr}:{rport}/contest-hardened-new"

    # build the hardened container images and qcow2 disk inside a temporary VM,
    # so that bootc-image-builder can run with --privileged (init-namespace root)
    # and podman build doesn't have to run nested when Contest runs in a container
    builder = virt.Guest(name="contest-builder")
    builder.import_cloud_image(vcpus=min(4, os.cpu_count() or 1))

    qcow2_path = Path(virt.GUEST_IMG_DIR) / f"{guest.name}.qcow2"
    with builder.booted():
        builder.wait_for_cloud_init()
        builder.ssh("dnf", "-y", "install", "podman", check=True)
        builder.ssh("mkdir", "-p", "/root/build", "/root/output", check=True)

        build_files = ["contest-pack.rpm", "remediation-old-ds.xml", "remediation-new-ds.xml"]
        if cleanup_sh:
            build_files.append(cleanup_sh)
        for src in build_files:
            builder.copy_to(src, "/root/build/")

        builder.ssh("podman", "pull", src_image, check=True)

        # build contest-hardened-* tagged images using the old and new datastreams,
        # storing the remediation ARFs in / inside each image
        build_image(
            builder, "remediation-old-ds.xml", "/remediation-old-arf.xml", "contest-hardened-old",
        )
        build_image(
            builder, "remediation-new-ds.xml", "/remediation-new-arf.xml", "contest-hardened-new",
        )

        # build the hardened image using a containerized builder
        builder.ssh(
            "podman", "container", "run",
            "--rm",
            "--privileged",
            "--security-opt", "label=type:unconfined_t",
            "--volume", "/root/output:/output",
            "--volume", "/var/lib/containers/storage:/var/lib/containers/storage",
            "quay.io/centos-bootc/bootc-image-builder",
            # arguments for the builder itself
            "build",
            "--type", "qcow2",
            "--local",
            # 'localhost/' prefix tells the builder to just use local image storage
            "localhost/contest-hardened-old",
            check=True,
        )

        # path inside the output dir seems to be hardcoded in bootc-image-builder
        builder.copy_from("/root/output/qcow2/disk.qcow2", qcow2_path)

        # push the new image directly to the host's local registry
        builder.ssh(
            "podman", "image", "push", "--tls-verify=false",
            "localhost/contest-hardened-new", guest_image_url,
            check=True,
        )

    # free up disk space before using the hardened guest
    builder.wipe()

    guest.import_image(qcow2_path, "qcow2")

    # boot up and scan the VM
    with guest.booted():
        # copy the old remediation ARF from the guest
        # we need to do this before switching the image, as it will be removed
        # by the bootc switch
        guest.copy_from("/remediation-old-arf.xml")
        guest.ssh(
            fr"""echo -e '[[registry]]\nlocation = "{raddr}:{rport}"\n"""
            r"""insecure = true\n' >> /etc/containers/registries.conf""",
        )

        # Run "bootc switch" to switch the image to the new one
        guest.ssh(f"bootc switch {guest_image_url}", check=True)

        # reboot the VM to apply the new image
        # we can't use guest.soft_reboot() here, because we don't have a guest agent
        guest.ssh("reboot")
        virt.wait_for_ssh(guest.ipaddr, guest.port, to_shutdown=True)
        virt.wait_for_ssh(guest.ipaddr, guest.port)

        # copy the original DS to the guest
        guest.copy_to(util.get_datastream(), "scan-ds.xml")
        # scan the remediated system
        proc, lines = guest.ssh_stream(
            f"oscap xccdf eval --profile {profile} --progress --report report.html"
            f" --results-arf scan-arf.xml scan-ds.xml",
        )
        oscap.report_from_verbose(lines, to_file="oscap.log")
        if proc.returncode not in [0,2]:
            raise RuntimeError(f"post-reboot oscap failed unexpectedly with {proc.returncode}")
        guest.copy_from("report.html")
        guest.copy_from("scan-arf.xml")
        guest.copy_from("/remediation-new-arf.xml")

results.report_and_exit(logs=[
    "report.html", "scan-arf.xml", "remediation-old-arf.xml", "remediation-new-arf.xml",
])

import os
import shutil
from pathlib import Path

from conf import remediation
from lib import oscap, podman, results, util, versions, virt

virt.Host.setup()

profile = util.get_test_name().rpartition("/")[2]
oscap_repo = os.environ.get("CONTEST_OSCAP_REPOFILE")

oscap.unselect_rules(util.get_datastream(), "remediation-ds.xml", remediation.excludes())

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

# prepare a Containerfile for making a hardened image
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
    COPY remediation-ds.xml /root/.
    # install and run oscap-im to harden the image
    RUN dnf -y install openscap-utils
    RUN oscap-im --profile '{profile}' \
        --results-arf /root/remediation-arf.xml /root/remediation-ds.xml
    # debug only: run a lint check but don't fail the build in case of any issues
    RUN bootc container lint || true
""")
cfile.add_ssh_pubkey(guest.ssh_pubkey)
cfile.write_to("Containerfile")

# build the hardened container image and qcow2 disk inside a temporary VM,
# so that bootc-image-builder can run with --privileged (init-namespace root)
# and podman build doesn't have to run nested when Contest runs in a container
builder = virt.Guest(name="contest-builder")
builder.import_cloud_image(vcpus=min(4, os.cpu_count() or 1))

qcow2_path = Path(virt.GUEST_IMG_DIR) / f"{guest.name}.qcow2"
with builder.booted():
    builder.wait_for_cloud_init()
    builder.ssh("dnf", "-y", "install", "podman", check=True)
    builder.ssh("mkdir", "-p", "/root/build", "/root/output", check=True)

    build_files = ["Containerfile", "contest-pack.rpm", "remediation-ds.xml"]
    if cleanup_sh:
        build_files.append(cleanup_sh)
    for src in build_files:
        builder.copy_to(src, "/root/build/")

    builder.ssh("podman", "pull", src_image, check=True)
    builder.ssh(
        "podman", "image", "build", "--tag", "contest-hardened", "/root/build",
        check=True,
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
        "localhost/contest-hardened",
        check=True,
    )

    # path inside the output dir seems to be hardcoded in bootc-image-builder
    builder.copy_from("/root/output/qcow2/disk.qcow2", qcow2_path)

# free up disk space before using the hardened guest
builder.wipe()

guest.import_image(qcow2_path, "qcow2")

# boot up and scan the VM
with guest.booted():
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
    guest.copy_from("remediation-arf.xml")
    guest.copy_from("scan-arf.xml")

results.report_and_exit(logs=["report.html", "remediation-arf.xml", "scan-arf.xml"])

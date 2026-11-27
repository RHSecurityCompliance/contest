import os
import shutil
from pathlib import Path

from conf import remediation
from lib import metadata, oscap, podman, results, util, versions, virt

virt.Host.setup()
podman.Host.setup()

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

# we can't use standard CaC/content style partitioning scheme because the
# space distribution is different and the installer runs out of space,
# so define this explicitly here for now
# - note that Anaconda requires a separate /boot for 'ostreecontainer',
#   otherwise it crashes on RHEL-66155
partitions = [
    ("/boot", 1000),
    ("/", 18000),
]

ks = virt.Kickstart(partitions=partitions)

# install the VM, using a locally-hosted podman registry serving
# the hardened image for Anaconda's ostreecontainer
with podman.Registry(host_addr=virt.NETWORK_HOST, guest_addr=virt.NETWORK_GUEST) as registry:
    raddr, rport = registry.get_guest_listen_addr()
    guest_image_url = f"{raddr}:{rport}/contest-hardened"

    # build the hardened container image inside a temporary VM, so that
    # podman build (and oscap-im remediation) runs in a clean OS environment
    # instead of nested when Contest itself runs in a container
    builder = virt.Guest(name="contest-builder")
    builder.import_cloud_image(vcpus=min(4, os.cpu_count() or 1))

    with builder.booted():
        builder.wait_for_cloud_init()
        builder.ssh("dnf", "-y", "install", "podman", check=True)
        builder.ssh("mkdir", "-p", "/root/build", check=True)

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

        # push the hardened image directly to the host's local registry
        builder.ssh(
            "podman", "image", "push", "--tls-verify=false",
            "localhost/contest-hardened", guest_image_url,
            check=True,
        )

    # free up disk space before installing the hardened guest
    builder.wipe()

    ks.append(f"ostreecontainer --url {guest_image_url}")
    # Anaconda doesn't expose ostree --insecure-skip-tls-verification,
    # work around it using registries.conf
    ks.add_pre(
        fr"""echo -e '[[registry]]\nlocation = "{raddr}:{rport}"\n"""
        r"""insecure = true\n' >> /etc/containers/registries.conf""",
    )
    guest.install_basic(
        kickstart=ks,
        # Anaconda installer may itself perform cryptographic operations so
        # it also needs to run with fips=1, see
        # https://docs.fedoraproject.org/en-US/bootc/security-and-hardening/
        kernel_args=["fips=1"] if "fips" in metadata.tags() else None,
    )

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

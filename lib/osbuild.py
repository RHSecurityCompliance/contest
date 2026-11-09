"""
Provides utilities for building Image Builder images and using them as virtual
machines.

Images are built via the 'image-builder' CLI inside a temporary builder VM,
not on the system running Contest, because building writes SELinux labels into
the image, which the kernel allows only from the initial user namespace - this
can never work when Contest itself runs in a container. The builder VM, created
from a CentOS Stream 10 cloud image (see virt.Guest.import_cloud_image()),
also provides a recent 'image-builder' regardless of the host OS version,
building images of the host OS from the host's repositories. It is removed
right after the build, before the built image is used as a VM.

The classes and methods are derived from lib.virt, but instead of installing
VMs via Guest.install(), they are created from images via Guest.create().

    from lib import osbuild, virt

    virt.Host.setup()
    g = osbuild.Guest()

    # optional
    blueprint = osbuild.Blueprint()
    blueprint.add_something( ... )

    g.create(blueprint=blueprint)

    with g.booted():
        g.ssh( ... )
        g.ssh( ... )

Snapshotting is currently not supported/tested with this approach.
"""

import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from lib import dnf, results, util, versions, virt

# image-builder build --image-size, in bytes; 100 GiB gives plenty of space
# for all profiles and partitions, e.g. STIG which uses 10 GiB /var/log/audit
# partition because of DISA requirements. The qcow2 image is sparse, so actual
# disk usage is much smaller.
QCOW2_IMAGE_SIZE = 100 * 1024**3
# minimum size of / in images built from oscap-generated blueprints,
# see translate_oscap_blueprint()
ROOT_MIN_SIZE = 20 * 1024**3


# this is using a different approach to class Kickstart or class RpmPack
# because of varying data types key/values of tables/arrays can have,
# ie. transforming python dict to
#   [customizations.openscap.tailoring]
#   unselected = [ "grub2_password" ]
# would require logic for quoting str(), for transforming arrays into [ ], etc.,
# so let's just append strings instead
class Blueprint:
    NAME = "contest_blueprint"
    TEMPLATE = util.dedent(fr"""
        name = "{NAME}"
        description = "Testing blueprint created by the Contest test suite"
        version = "1.0.0"
    """)

    def __init__(self, template=TEMPLATE):
        self.assembled = f"{template}\n\n" if template else ""

    def add_user(self, name, *, password=None, groups=None, ssh_pubkey=None):
        self.assembled += "[[customizations.user]]\n"
        self.assembled += f'name = "{name}"\n'
        if password:
            self.assembled += f'password = "{password}"\n'
        if groups:
            groups_str = ",".join(f'"{x}"' for x in groups)
            self.assembled += f"groups = [ {groups_str} ]\n"
        if ssh_pubkey:
            self.assembled += f'key = "{ssh_pubkey}"\n'

    def add_package(self, name):
        self.assembled += util.dedent(fr"""
            [[packages]]
            name = "{name}"
        """) + "\n"

    def add_package_group(self, name):
        self.assembled += util.dedent(fr"""
            [[groups]]
            name = "{name}"
        """) + "\n"

    def add_partition(self, mountpoint, minsize):
        self.assembled += util.dedent(fr"""
            [[customizations.filesystem]]
            mountpoint = "{mountpoint}"
            minsize = {minsize}
        """) + "\n"

    def set_openscap_datastream(self, ds_file):
        pre, header, post = self.assembled.partition("\n[customizations.openscap]\n")
        if not header:
            raise ValueError("openscap section not found")
        self.assembled = "\n".join([
            pre,
            header.strip("\n"),
            f'datastream = "{ds_file}"',
            post,
        ])

    @contextlib.contextmanager
    def to_tmpfile(self):
        bp = self.assembled
        util.log(f"using blueprint:\n{textwrap.indent(bp, '    ')}")
        with tempfile.NamedTemporaryFile(mode="w") as f:
            f.write(bp)
            f.flush()
            yield Path(f.name)


# temporary guest building the images
BUILDER_NAME = "contest-image-builder"
BUILDER_PACKAGES = ["image-builder", "osbuild", "osbuild-depsolve-dnf", "rsync"]


def _resolve_distro(builder):
    """
    Return an image-builder distribution name matching the host OS, as known
    to image-builder inside a running 'builder' guest.

    An in-development RHEL minor version might not be known to image-builder
    yet, so fall back to the newest known minor version of the same major
    version. Since the host's repositories are always used for building,
    this affects only the distribution definition (default packages,
    partitioning, etc.).
    """
    major, minor = versions.rhel.major, versions.rhel.minor
    if versions.rhel.is_centos():
        return f"centos-{major}"

    proc = builder.ssh(
        "image-builder list --format=json --filter type:qcow2",
        stdout=subprocess.PIPE, text=True, check=True,
    )
    known = {entry["distro"]["name"] for entry in json.loads(proc.stdout)}

    distro = f"rhel-{major}.{minor}"
    if distro in known:
        return distro

    same_major = (name for name in known if name.startswith(f"rhel-{major}."))
    fallback = max(same_major, key=lambda name: int(name.rpartition(".")[2]), default=None)
    if not fallback:
        raise RuntimeError(f"image-builder knows neither {distro} nor any rhel-{major}.*")
    util.log(f"image-builder doesn't know {distro}, using {fallback} instead")
    return fallback


def build_image(blueprint, image_path, log_path, *, extra_repo=None, image_size=None):
    """
    Build a qcow2 image from 'blueprint' (a Blueprint instance) inside
    a temporary builder guest, using the host's repositories, and copy it
    to 'image_path' on the host, with its build log to 'log_path'.

    The build log is also uploaded as a test log, even if the build fails.

    'extra_repo' is a host directory with YUM/DNF repository metadata
    (ie. from RpmPack.build_as_repo()), providing packages that are not
    in the host's repositories, ie. the custom RpmPack RPM.

    'image_size' is the size of the image in bytes.

    The builder guest is removed after a successful build, but left in place
    (shut down) after a failure, for debugging.
    """
    builder = virt.Guest(name=BUILDER_NAME)
    builder.import_cloud_image(vcpus=min(4, os.cpu_count() or 1))

    with builder.booted():
        # wait for cloud-init to finish the first boot setup (ie. growing
        # the root filesystem), 2 means it finished with recoverable errors
        proc = builder.ssh("cloud-init", "status", "--wait")
        if proc.returncode not in [0,2]:
            raise RuntimeError(f"cloud-init failed with {proc.returncode}")
        builder.ssh("dnf", "-y", "install", *BUILDER_PACKAGES, check=True)

        with blueprint.to_tmpfile() as bp_file:
            builder.copy_to(bp_file, "/root/blueprint.toml")

        cmd = [
            "image-builder", "build", "qcow2",
            "--distro", _resolve_distro(builder),
            "--blueprint", "/root/blueprint.toml",
            "--output-dir", "/root/output", "--output-name", "image",
            "--with-buildlog", "--progress", "verbose",
            # only print manifest warnings (ie. about the builder not running
            # in FIPS mode when building a FIPS image) instead of failing
            "--ignore-warnings",
            # repositories used only for building, not added to the image
            *(f"--force-repo={url}" for _, url in dnf.repo_urls()),
        ]
        if extra_repo:
            # copy the repository into the guest and use it from there via
            # file://, as it exists only on the host; add it as --force-repo,
            # because --extra-repo is ignored when --force-repo is used
            builder.rsync_to(f"{extra_repo}/", "/root/extra-repo")
            cmd.append("--force-repo=file:///root/extra-repo")
        if image_size:
            cmd.append(f"--image-size={image_size}")

        util.log(f"building image inside {builder.name}")
        proc, lines = builder.ssh_stream(*cmd, stderr=subprocess.STDOUT)
        for line in lines:
            sys.stdout.write(f"{line}\n")
            sys.stdout.flush()

        # copy and upload the build log before checking for success, as it is
        # needed for debugging failures too (it doesn't exist if image-builder
        # failed before running osbuild, ie. when depsolving)
        if builder.ssh("test", "-f", "/root/output/image.buildlog").returncode == 0:
            builder.copy_from("/root/output/image.buildlog", log_path)
            results.add_log(log_path)
        if proc.returncode != 0:
            raise RuntimeError(f"image-builder failed with {proc.returncode}")

        builder.copy_from("/root/output/image.qcow2", image_path)

    # free up disk space for the guest using the built image
    builder.wipe()


class Guest(virt.Guest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.osbuild_log = f"{virt.GUEST_IMG_DIR}/{self.name}-osbuild.txt"

    def wipe(self):
        super().wipe()
        log = Path(self.osbuild_log)
        if log.exists():
            log.unlink()

    def install(self, *args, **kwargs):
        raise NotImplementedError("install() is not supported, use create()")

    def create_basic(self, *, blueprint=None, extra_repo=None, **kwargs):
        """
        Create a guest disk image via build_image(), and import it as a new
        guest domain into libvirt.

        If 'blueprint' is given as a 'class Blueprint' instance, it is used
        for further customizations instead of a fresh Blueprint instance.

        'extra_repo' is passed to build_image().
        """
        util.log(f"creating guest {self.name}")

        if not blueprint:
            blueprint = Blueprint()

        image_path = Path(f"{virt.GUEST_IMG_DIR}/{self.name}.img")
        build_image(
            blueprint, image_path, self.osbuild_log,
            extra_repo=extra_repo, image_size=QCOW2_IMAGE_SIZE,
        )

        # import the created qcow2 image as a VM
        self.import_image(image_path, "qcow2", **kwargs)

    def create(self, *, blueprint=None, rpmpack=None, **kwargs):
        """
        Create a guest disk image via build_image(), suitable for scanning
        via openscap.

        If custom 'rpmpack' is specified (RpmPack instance), it is used instead
        of a self-made instance.
        """
        # remove any previously installed guest
        self.wipe()

        if not blueprint:
            blueprint = Blueprint()

        # implicitly install openscap-scanner, like virt.Guest.install()
        blueprint.add_package("openscap-scanner")

        # generate an ssh key the same way as virt.Guest
        self.generate_ssh_keypair()
        blueprint.add_user("root", password=virt.GUEST_LOGIN_PASS, ssh_pubkey=self.ssh_pubkey)

        # osbuild doesn't support running Anaconda %post-style custom
        # scripts, the only way to run additional shell code is via
        # RPM scriptlets, so add custom guest setup via RpmPack
        pack = rpmpack or util.RpmPack()
        pack.add_host_repos()
        pack.add_sshd_late_start()
        # inherited from virt.Guest
        pack.requires += self.GUEST_REQUIRES
        with pack.build_as_repo() as repo:
            # ensure the custom RPM is added during image building
            blueprint.add_package(util.RpmPack.NAME)
            # build qcow2 and import it, using the repository with the custom
            # RPM in addition to the host's repositories
            self.create_basic(blueprint=blueprint, extra_repo=repo, **kwargs)


def translate_oscap_blueprint(lines, datastream):
    """
    Parse (and tweak) a blueprint generated via 'oscap xccdf generate fix'.
    """
    bp_text = "\n".join(lines)

    # Partitioning mode defaults to auto-lvm which uses lvm because we use
    # filesystem customizations in blueprints; root LV then stays near the
    # 1 GiB / + 2 GiB /usr hard-coded minimum size with free space left in the VG.
    # Switch to raw layout which grows the / partition to fill the disk, see
    # https://osbuild.org/docs/user-guide/partitioning/
    # https://osbuild.org/docs/user-guide/blueprint-reference/#partitioning-mode
    bp_new = re.sub(
        r'^partitioning_mode\s*=\s*"[^"]*"\s*$',
        'partitioning_mode = "raw"',
        bp_text,
        count=1,
        flags=re.MULTILINE,
    )
    if bp_new != bp_text:
        bp_text = bp_new
    elif not re.search(r'^partitioning_mode\s*=\s*"raw"\s*$', bp_text, flags=re.MULTILINE):
        bp_text, inserted = re.subn(
            r"^(\[customizations\]\s*\n)",
            r'\1partitioning_mode = "raw"\n',
            bp_text,
            count=1,
            flags=re.MULTILINE,
        )
        if not inserted:
            bp_text = re.sub(
                r"^(version = .*\n)",
                r'\1\n[customizations]\npartitioning_mode = "raw"\n',
                bp_text,
                count=1,
                flags=re.MULTILINE,
            )

    blueprint = Blueprint(template=bp_text)

    # image-builder currently ignores partitioning_mode and always uses
    # auto-lvm, leaving the root LV at its minimum size, so request a minimum
    # size of / explicitly (with raw, / still grows to fill the disk), unless
    # the blueprint already has a / filesystem customization, see
    # https://github.com/osbuild/image-builder/issues/2823
    # TODO: remove this and ROOT_MIN_SIZE once the issue is fixed, tracked in
    #       https://github.com/RHSecurityCompliance/contest/issues/706
    if not re.search(r'^mountpoint\s*=\s*"/"\s*$', bp_text, flags=re.MULTILINE):
        blueprint.add_partition("/", ROOT_MIN_SIZE)

    # add openscap hardening, honor global excludes
    blueprint.set_openscap_datastream(datastream)

    return blueprint

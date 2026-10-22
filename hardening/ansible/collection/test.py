import atexit
import os
import subprocess
import sys
from pathlib import Path

from conf import partitions, remediation
from lib import ansible, metadata, oscap, results, util, versions, virt

# Replicate the downstream (RPM) build of the RHEL hardening Ansible collection.
# See https://gitlab.com/redhat/centos-stream/rpms/scap-security-guide/-/merge_requests/90
COLLECTION_PRODUCTS = ["rhel8", "rhel9", "rhel10"]
COLLECTION_NAMESPACE = "redhat"
COLLECTION_NAME = "rhel_hardening_roles"
COMMUNITY_GENERAL_VERSION = "11.2.1"

DOWNSTREAM_CMAKE_OPTS = {
    "SSG_PRODUCT_DEFAULT:BOOL": "OFF",
    **{f"SSG_PRODUCT_{product.upper()}:BOOL": "ON" for product in COLLECTION_PRODUCTS},
    "SSG_ANSIBLE_PLAYBOOKS_ENABLED:BOOL": "ON",
    "SSG_ANSIBLE_ROLES_ENABLED:BOOL": "ON",
    "SSG_ANSIBLE_COLLECTION_ENABLED:BOOL": "OFF",
    "SSG_ANSIBLE_PLAYBOOKS_PER_RULE_ENABLED:BOOL": "OFF",
    "SSG_BASH_SCRIPTS_ENABLED:BOOL": "OFF",
    "SSG_SEPARATE_SCAP_FILES_ENABLED:BOOL": "OFF",
    "SSG_BUILD_SCAP_12_DS:BOOL": "OFF",
    "SSG_BUILD_DISA_DELTA_FILES:BOOL": "OFF",
    "SSG_CENTOS_DERIVATIVES_ENABLED:BOOL": "OFF",
    "SSG_SCIENTIFIC_LINUX_DERIVATIVES_ENABLED:BOOL": "OFF",
    "SSG_SCE_ENABLED:BOOL": "ON",
    "SSG_SCAP_VALIDATION_ENABLED:BOOL": "OFF",
    "SSG_LINKCHECKER_VALIDATION_ENABLED:BOOL": "OFF",
    "SSG_OVAL_SCHEMATRON_VALIDATION_ENABLED:BOOL": "OFF",
    "SSG_SHELLCHECK_BASH_FIXES_VALIDATION_ENABLED:BOOL": "OFF",
    "SSG_BATS_TESTS_ENABLED:BOOL": "OFF",
}


def ensure_python_deps():
    """
    Make sure the interpreter running this test can run the content utils.

    They import 'ssg' (made available via PYTHONPATH) and need jinja2 and a
    PyYAML new enough to support 'sort_keys'. The latter is not always
    installed for the Python running the test, e.g. on RHEL-8 where the
    content build uses the old system Python.
    """
    probe = "import jinja2, yaml; yaml.safe_dump({}, sort_keys=False)"
    if util.subprocess_run([sys.executable, "-c", probe]).returncode == 0:
        return

    # Install via CONTEST_PYTHON (sys.executable), not bare pip3 - on RHEL-8/9
    # pip3 targets the older system Python.
    if util.subprocess_run([sys.executable, "-m", "pip", "--version"]).returncode != 0:
        util.subprocess_run([sys.executable, "-m", "ensurepip", "--upgrade"], check=True)
    util.subprocess_run(
        [sys.executable, "-m", "pip", "install", "jinja2", "pyyaml>=5.1"],
        check=True,
    )


def build_collection(content_dir):
    """
    Build the collection the same way the downstream RPM does, and return the
    directory holding the generated 'ansible_collections' tree.
    """
    build_dir = content_dir / util.CONTENT_BUILD_DIR
    product = f"rhel{versions.rhel.major}"

    # The downstream build is guarded out on CentOS Stream, so only RHEL is
    # expected to get here. The current product needs its datastream for the
    # post-remediation scan.
    make_targets = [
        *(f"generate-all-profile-playbooks-{p}" for p in COLLECTION_PRODUCTS),
        f"generate-ssg-{product}-ds.xml",
    ]
    util.build_content(content_dir, DOWNSTREAM_CMAKE_OPTS, make_targets=make_targets)

    # paths must be absolute because the content scripts run with cwd=content_dir
    roles_workdir = Path.cwd() / "ansible-roles"
    role_args = []
    env = os.environ | {
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(content_dir), os.environ.get("PYTHONPATH")]),
        ),
    }
    ensure_python_deps()
    for p in COLLECTION_PRODUCTS:
        product_roles = roles_workdir / p
        util.subprocess_run(
            [
                sys.executable, "utils/ansible_playbook_to_role.py",
                "--build-playbooks-dir", build_dir / "ansible",
                "--dry-run", product_roles,
                "--product", p,
            ],
            cwd=content_dir, env=env, check=True, stderr=subprocess.PIPE,
        )
        role_args += ["--roles-dir", product_roles]

    collection_dir = Path.cwd() / "collection"
    util.subprocess_run(
        [
            sys.executable, "utils/ansible_roles_to_collection.py",
            *role_args,
            "--community-general-version", COMMUNITY_GENERAL_VERSION,
            "--output-dir", collection_dir,
            "--target", "hub",
            "--collection", COLLECTION_NAME,
        ],
        cwd=content_dir, env=env, check=True, stderr=subprocess.PIPE,
    )

    return collection_dir


def use_collection(collection_dir):
    """Prepend the generated collection to Ansible's collection search path."""
    paths = [str(collection_dir)]
    if existing := os.environ.get("ANSIBLE_COLLECTIONS_PATH"):
        paths.append(existing)
    else:
        # mimic the Ansible default, which an env var would otherwise override
        paths += [
            str(Path.home() / ".ansible" / "collections"),
            "/usr/share/ansible/collections",
        ]
    os.environ["ANSIBLE_COLLECTIONS_PATH"] = os.pathsep.join(paths)


profile = util.get_test_name().rpartition("/")[2]
product = f"rhel{versions.rhel.major}"
role = f"{COLLECTION_NAMESPACE}.{COLLECTION_NAME}.{product}_{profile.replace('-', '_')}"

ansible.install_deps()
virt.Host.setup()

guest_tag = virt.calculate_guest_tag(metadata.tags())
g = virt.Guest(guest_tag)

if not g.is_installed():
    ks = virt.Kickstart(partitions=partitions.partitions)
    g.install(kickstart=ks)

g.prepare_for_snapshot()
atexit.register(g.cleanup_snapshot)

with util.get_source_content() as content_dir:
    collection_dir = build_collection(content_dir)
    use_collection(collection_dir)
    collection_root = (
        collection_dir / "ansible_collections" / COLLECTION_NAMESPACE / COLLECTION_NAME
    )

    if not (collection_root / "roles" / f"{product}_{profile.replace('-', '_')}").is_dir():
        raise RuntimeError(f"profile role {role} was not generated in the collection")

    datastream = util.get_datastream(content_dir=content_dir)

    # the VM guest ssh code doesn't use $HOME/.known_hosts, so Ansible blocks
    # on trying to accept its ssh key - tell it to ignore this
    os.environ["ANSIBLE_HOST_KEY_CHECKING"] = "False"

    with g.snapshotted():
        # a plain playbook that pulls in the collection role, as downstream
        # users would do
        playbook = Path("playbook.yml")
        playbook.write_text(
            "---\n"
            "- hosts: all\n"
            "  roles:\n"
            f"    - {role}\n",
        )

        skip_tags = ",".join(remediation.excludes())
        skip_tags_arg = ["--skip-tags", skip_tags] if skip_tags else []
        ansible_cmd = [
            "ansible-playbook", "-v", "-i", f"{g.ipaddr},",
            "-u", virt.GUEST_SSH_USER, "-c", "ssh", "-e", f"ansible_port={g.port}",
            "--private-key", g.ssh_keyfile_path,
            *skip_tags_arg,
            playbook,
        ]
        proc, lines = util.subprocess_stream(ansible_cmd, stderr=subprocess.STDOUT)
        ansible.report_from_output(lines, to_file="ansible-playbook.log")
        if proc.returncode != 0:
            results.report_and_exit("fail", note=f"ansible-playbook failed with {proc.returncode}")
        g.soft_reboot()

        # scan the remediated system
        g.copy_to(datastream, "scan-ds.xml")
        proc, lines = g.ssh_stream(
            f"oscap xccdf eval --profile {profile} --progress --report report.html"
            f" --results-arf scan-arf.xml scan-ds.xml",
        )
        oscap.report_from_verbose(lines, to_file="oscap.log")
        if proc.returncode not in [0, 2]:
            raise RuntimeError(f"post-reboot oscap failed unexpectedly with {proc.returncode}")

        g.copy_from("report.html")
        g.copy_from("scan-arf.xml")

results.report_and_exit(logs=["report.html", "scan-arf.xml"])

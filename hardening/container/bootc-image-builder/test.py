#!/usr/bin/python3

#import contextlib
import shutil
from pathlib import Path

from lib import results, oscap, osbuild, virt, podman, util
from conf import remediation

#
# TODO: specify --root and --storage-opt for all podman commands,
#       have ie. /var/lib/containers/contest-storage to not conflict
#       with other images (image names) that might be on the system
#       while having a storage share-able across tests
#

#podman.Host.setup()
virt.Host.setup()

_, variant, profile = util.get_test_name().rsplit('/', 2)

oscap.unselect_rules(util.get_datastream(), 'remediation-ds.xml', remediation.excludes())


pull_images = [
    'quay.io/centos-bootc/centos-bootc:stream9',
    'quay.io/centos-bootc/bootc-image-builder:latest',
]
for img in pull_images:
    # --quiet because screen-redrawing progress bars don't work well with logs
    podman.podman('image', 'pull', '--quiet', img)


# TODO: Containerfile, needs 'podman' module support for 'class Repository'
#       using a locally-hosted HTTP server
# TODO: probably use localhost/ for pulled images ?
containerfile_text = util.dedent(fr'''
    FROM quay.io/centos-bootc/centos-bootc:stream9
    RUN ["dnf", "-y", "install", "dnf-plugins-core"]
    RUN ["dnf", "-y", "copr", "enable", "packit/OpenSCAP-openscap-2170", "centos-stream-9-x86_64"]
    RUN ["dnf", "-y", "install", "openscap-utils"]
    COPY remediation-ds.xml /root/.
    RUN ["oscap-bootc", "--profile", "{profile}", "/root/remediation-ds.xml"]
''')

Path('Containerfile').write_text(containerfile_text)
podman.podman('image', 'build', '--tag', 'bootc-centos-openscap', '.')


guest = virt.Guest()
guest.wipe()
guest.generate_ssh_keypair()

# TODO: probably move this to class Containerfile, managed by the 'podman' module,
#       so sshkey insertion is generic across all container-based workflows
blueprint = osbuild.Blueprint(template='')
blueprint.add_user('root', password=virt.GUEST_LOGIN_PASS, ssh_pubkey=guest.ssh_pubkey)

#c = podman.Container('quay.io/centos-bootc/bootc-image-builder:latest')


bootc_output_dir = Path(virt.GUEST_IMG_DIR) / 'bootc-image-builder-output'
if bootc_output_dir.exists():
    shutil.rmtree(bootc_output_dir)
bootc_output_dir.mkdir(parents=True)

#with contextlib.ExitStack() as stack:
#with tempfile.NamedTemporaryFile(mode='w', suffix='.toml') as config_toml:
#    Path(config_toml).write_text(blueprint

with blueprint.to_tmpfile() as config_toml:
    # TODO: maybe refer to pulled images as localhost/ so they don't get re-queried?
    #       (and drop --pull never)
    podman.podman(
        'container', 'run',
        '--rm',
        '--pull', 'never',
        '--privileged',
        '--security-opt', 'label=type:unconfined_t',
        '--volume', f'{config_toml}:/config.toml:ro',
        '--volume', f'{bootc_output_dir}:/output',
        '--volume', '/var/lib/containers/storage:/var/lib/containers/storage',
        'quay.io/centos-bootc/bootc-image-builder:latest',
        'build',
        '--type', 'qcow2',
        '--local',
        'localhost/bootc-centos-openscap:latest',
    )
#        'quay.io/centos-bootc/centos-bootc:stream9',

# seems to be hardcoded by bootc-image-builder
qcow2_path = bootc_output_dir / 'qcow2' / 'disk.qcow2'

guest.import_image(qcow2_path, 'qcow2')


with guest.booted():
    # copy the original DS to the guest
    guest.copy_to(util.get_datastream(), 'scan-ds.xml')
    # scan the remediated system
    proc, lines = guest.ssh_stream(
        f'oscap xccdf eval --profile {profile} --progress --report report.html'
        f' --results-arf results-arf.xml scan-ds.xml'
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0,2]:
        raise RuntimeError("post-reboot oscap failed unexpectedly")

    guest.copy_from('report.html')
    guest.copy_from('results-arf.xml')

util.subprocess_run(['gzip', '-9', 'results-arf.xml'], check=True)

results.report_and_exit(logs=['report.html', 'results-arf.xml.gz'])

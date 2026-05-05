#!/usr/bin/python3

import shutil
import subprocess

from pathlib import Path

from lib import results, metadata, oscap, podman, util

SCANNER_IMAGE = 'quay.io/hummingbird/openscap:latest'
podman.podman('pull', SCANNER_IMAGE)

IMAGE = 'openjdk'
profile = util.get_test_name().rpartition('/')[2]
if 'fips' in metadata.tags():
    image_variant = 'latest-fips'
else:
    image_variant = 'latest'
image_id = f'quay.io/hummingbird/{IMAGE}:{image_variant}'
podman.podman('pull', image_id)

with util.get_source_content() as content_dir:
    # Hummingbird is a separate product in ComplianceAsCode/content
    util.build_content(
        content_dir,
        {
            'SSG_PRODUCT_HUMMINGBIRD:BOOL': 'ON',
        },
    )
    ds_path = content_dir / util.CONTENT_BUILD_DIR / 'ssg-hummingbird-ds.xml'
    if not ds_path.exists():
        raise RuntimeError(f"Datastream not found: {ds_path}")
    shutil.copy(ds_path, Path.cwd())
    proc, lines = util.subprocess_stream(
        [
            'podman', 'run', '--rm',
            '--cap-add', 'SYS_CHROOT',
            '--mount', f'type=image,source={image_id},destination=/target',
            '-e', 'OSCAP_PROBE_ROOT=/target',
            '-v', f'{Path.cwd()}:/ssg:z,U',
            SCANNER_IMAGE,
            'xccdf', 'eval', '--progress',
            '--profile', profile,
            '--results-arf', '/ssg/scan-arf.xml',
            '--report', '/ssg/report.html',
            '/ssg/ssg-hummingbird-ds.xml',
        ],
        stderr=subprocess.STDOUT,
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0, 2]:
        raise RuntimeError("oscap failed unexpectedly")

results.add_log('report.html', 'scan-arf.xml')
results.report_and_exit()

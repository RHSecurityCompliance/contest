#!/usr/bin/python3

import subprocess

from lib import results, metadata, oscap, podman, util

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

    proc, lines = util.subprocess_stream(
        [
            'oscap-podman', image_id, 'xccdf', 'eval', '--profile', profile, '--progress',
            '--report', 'report.html', '--results-arf', 'scan-arf.xml', ds_path,
        ],
        stderr=subprocess.STDOUT,
    )
    oscap.report_from_verbose(lines)
    if proc.returncode not in [0, 2]:
        raise RuntimeError("oscap failed unexpectedly")

results.report_and_exit(logs=['report.html', 'scan-arf.xml'])

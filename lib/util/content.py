from pathlib import Path

from .. import versions


def get_datastream():
    base_dir = Path('/usr/share/xml/scap/ssg/content')
    if versions.rhel:
        return base_dir / f'ssg-rhel{versions.rhel.major}-ds.xml'
    else:
        raise RuntimeError("cannot find datastream for non-RHEL")


def get_playbook(profile):
    base_dir = Path('/usr/share/scap-security-guide/ansible')
    if versions.rhel:
        return base_dir / f'rhel{versions.rhel.major}-playbook-{profile}.yml'
    else:
        raise RuntimeError("cannot find playbook for non-RHEL")


def get_kickstart(profile):
    base_dir = Path('/usr/share/scap-security-guide/kickstart')
    if versions.rhel:
        return base_dir / f'ssg-rhel{versions.rhel.major}-{profile}-ks.cfg'
    else:
        raise RuntimeError("cannot find kickstart for non-RHEL")

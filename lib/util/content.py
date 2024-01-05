from pathlib import Path

from ..versions import rhel


def get_datastream():
    base_dir = Path('/usr/share/xml/scap/ssg/content')
    if rhel.is_true_rhel():
        return base_dir / f'ssg-rhel{rhel.major}-ds.xml'
    elif rhel.is_centos():
        if rhel <= 8:
            return base_dir / f'ssg-centos{rhel.major}-ds.xml'
        else:
            return base_dir / f'ssg-cs{rhel.major}-ds.xml'
    else:
        raise RuntimeError("cannot find datastream for testing")


def get_playbook(profile):
    base_dir = Path('/usr/share/scap-security-guide/ansible')
    if rhel.is_true_rhel():
        return base_dir / f'rhel{rhel.major}-playbook-{profile}.yml'
    elif rhel.is_centos():
        if rhel <= 8:
            return base_dir / f'centos{rhel.major}-playbook-{profile}.yml'
        else:
            return base_dir / f'cs{rhel.major}-playbook-{profile}.yml'
    else:
        raise RuntimeError("cannot find playbook for testing")


def get_kickstart(profile):
    base_dir = Path('/usr/share/scap-security-guide/kickstart')
    # RHEL and CentOS Stream both use 'ssg-rhel*' files
    if rhel:
        return base_dir / f'ssg-rhel{rhel.major}-{profile}-ks.cfg'
    else:
        raise RuntimeError("cannot find kickstart for testing")

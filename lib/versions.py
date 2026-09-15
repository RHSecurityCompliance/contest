import math
import platform

# cache /etc/os-release on a module-wide basis
_os_release = {}


def _update_os_release():
    if _os_release:
        return
    _os_release.update(platform.freedesktop_os_release())


class _Rhel:
    def __init__(self, version=None):
        if version is None:
            _update_os_release()
            version = _os_release['VERSION_ID']

        self.major, self.minor = self._parse_version(version)
        # to make version comparison on CentOS Stream possible we assign
        # it a minor version of math.inf as CentOS Stream is always the
        # latest minor version of RHEL
        if self.is_centos():
            self.minor = math.inf

    @staticmethod
    def is_true_rhel():
        return _os_release['ID'] == 'rhel'

    @staticmethod
    def is_centos():
        return _os_release['ID'] == 'centos'

    @staticmethod
    def __bool__():
        return _os_release['ID'] in ['rhel', 'centos']

    @staticmethod
    def _parse_version(version):
        major, _, minor = str(version).partition('.')
        return (int(major), int(minor) if minor else None)

    def __eq__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None:
            return bool(self) and self.major == other_major
        return bool(self) and ((self.major == other_major) and (self.minor == other_minor))

    def __ne__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None:
            return bool(self) and self.major != other_major
        return bool(self) and ((self.major != other_major) or (self.minor != other_minor))

    def __lt__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None:
            return bool(self) and self.major < other_major
        return bool(self) and (
            (self.major < other_major) or
            (self.major == other_major and self.minor < other_minor)
        )

    def __le__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None:
            return bool(self) and self.major <= other_major
        return bool(self) and (
            (self.major < other_major) or
            (self.major == other_major and self.minor <= other_minor)
        )

    def __gt__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None:
            return bool(self) and self.major > other_major
        return bool(self) and (
            (self.major > other_major) or
            (self.major == other_major and self.minor > other_minor)
        )

    def __ge__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None:
            return bool(self) and self.major >= other_major
        return bool(self) and (
            (self.major > other_major) or
            (self.major == other_major and self.minor >= other_minor)
        )

    def __str__(self):
        if self.minor:
            return f'{self.major}.{self.minor}'
        else:
            return str(self.major)


rhel = _Rhel()

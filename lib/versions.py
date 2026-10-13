import math
import platform


class _Rhel:
    def __init__(self, version=None):
        self.os_release = platform.freedesktop_os_release()

        if version is None:
            version = self.os_release["VERSION_ID"]

        self.major, self.minor = self._parse_version(version)
        # to make version comparison on CentOS Stream possible we assign
        # it a minor version of math.inf as CentOS Stream is always the
        # latest minor version of RHEL
        if self.is_centos():
            self.minor = math.inf

    def is_true_rhel(self):
        return self.os_release["ID"] == "rhel"

    def is_centos(self):
        return self.os_release["ID"] == "centos"

    @staticmethod
    def _parse_version(version):
        major, _, minor = str(version).partition(".")
        return (int(major), int(minor) if minor else None)

    def __eq__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None:
            return self.major == other_major
        return self.major == other_major and self.minor == other_minor

    def __ne__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None:
            return self.major != other_major
        return self.major != other_major or self.minor != other_minor

    def __lt__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None or self.minor is None:
            return self.major < other_major
        return (
            self.major < other_major or
            (self.major == other_major and self.minor < other_minor)
        )

    def __le__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None or self.minor is None:
            return self.major <= other_major
        return (
            self.major < other_major or
            (self.major == other_major and self.minor <= other_minor)
        )

    def __gt__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None or self.minor is None:
            return self.major > other_major
        return (
            self.major > other_major or
            (self.major == other_major and self.minor > other_minor)
        )

    def __ge__(self, other):
        other_major, other_minor = self._parse_version(other)
        if other_minor is None or self.minor is None:
            return self.major >= other_major
        return (
            self.major > other_major or
            (self.major == other_major and self.minor >= other_minor)
        )

    def __str__(self):
        if self.minor:
            return f"{self.major}.{self.minor}"
        else:
            return str(self.major)


rhel = _Rhel()

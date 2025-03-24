# cache /etc/os-release on a module-wide basis
_os_release = {}


def _update_os_release():
    if _os_release:
        return
    with open('/etc/os-release') as f:
        for line in f:
            if not line.strip():
                continue
            key, value = line.rstrip().split('=', 1)
            value = value.strip('"')
            _os_release[key] = value


class _Rhel:
    def __init__(self, version=None):
        if version is None:
            _update_os_release()
            version = _os_release['VERSION_ID']

        version = str(version)
        major, _, minor = version.partition('.')
        self.major = int(major)
        self.minor = int(minor) if minor else None

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
        if isinstance(version, _Rhel):
            return version
        return _Rhel(version)

    def __eq__(self, other):
        other = self._parse_version(other)
        if other.minor is None:
            return bool(self) and self.major == other.major
        return bool(self) and ((self.major == other.major) and (self.minor == other.minor))

    def __ne__(self, other):
        other = self._parse_version(other)
        if other.minor is None:
            return bool(self) and self.major != other.major
        return bool(self) and ((self.major != other.major) or (self.minor != other.minor))

    def __lt__(self, other):
        other = self._parse_version(other)
        if other.minor is None:
            return bool(self) and self.major < other.major
        return bool(self) and (
            (self.major < other.major) or
            (self.major == other.major and self.minor < other.minor)
        )

    def __le__(self, other):
        other = self._parse_version(other)
        if other.minor is None:
            return bool(self) and self.major <= other.major
        return bool(self) and (
            (self.major < other.major) or
            (self.major == other.major and self.minor <= other.minor)
        )

    def __gt__(self, other):
        other = self._parse_version(other)
        if other.minor is None:
            return bool(self) and self.major > other.major
        return bool(self) and (
            (self.major > other.major) or
            (self.major == other.major and self.minor > other.minor)
        )

    def __ge__(self, other):
        other = self._parse_version(other)
        if other.minor is None:
            return bool(self) and self.major >= other.major
        return bool(self) and (
            (self.major > other.major) or
            (self.major == other.major and self.minor >= other.minor)
        )

    def __str__(self):
        if self.minor:
            return f'{self.major}.{self.minor}'
        else:
            return str(self.major)


rhel = _Rhel()

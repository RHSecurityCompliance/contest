import rpm


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


class _RpmVerCmp:
    # needs:
    #   self.__bool__
    #   self.version
    #   self.release

    def compare(self, other):
        if not isinstance(other, str):
            other = str(other)
        other_version, _, other_release = other.partition('-')
        ours = (None, self.version, self.release)
        theirs = (None, other_version, other_release if other_release else None)
        return rpm.labelCompare(ours, theirs)

    def __lt__(self, other):
        return bool(self) and self.compare(other) < 0

    def __le__(self, other):
        return bool(self) and self.compare(other) <= 0

    def __eq__(self, other):
        return bool(self) and self.compare(other) == 0

    def __ne__(self, other):
        return bool(self) and self.compare(other) != 0

    def __ge__(self, other):
        return bool(self) and self.compare(other) >= 0

    def __gt__(self, other):
        return bool(self) and self.compare(other) > 0

    def __str__(self):
        if self.release:
            return f'{self.version}-{self.release}'
        else:
            return self.version


class _Rhel(_RpmVerCmp):
    def __init__(self):
        _update_os_release()
        self.version = _os_release['VERSION_ID']
        self.release = None
        self.major, self.minor = self._major_minor()

    def __bool__(self):
        return _os_release['ID'] == 'rhel'

    def compare(self, other):
        # if one number is given, treat it as a RHEL major version
        if isinstance(other, int):
            return self.major - other
        else:
            return super().compare(other)

    @staticmethod
    def _major_minor():
        v = _os_release['VERSION_ID'].split('.')
        if len(v) == 1:
            return (int(v[0]), None)
        else:
            return (int(v[0]), int(v[1]))


class _Rpm(_RpmVerCmp):
    def __init__(self, name):
        ts = rpm.TransactionSet()
        mi = ts.dbMatch('name', name)
        try:
            p = next(mi)
            # RHEL-7 rpm has these as bytes, for some reason
            self.version = p['version'] if isinstance(p['version'], str) else p['version'].decode()
            self.release = p['release'] if isinstance(p['release'], str) else p['release'].decode()
            self._installed = True
        except StopIteration:
            self._installed = False

    def __bool__(self):
        return self._installed


rhel = _Rhel()
oscap = _Rpm('openscap-scanner')
ssg = _Rpm('scap-security-guide')

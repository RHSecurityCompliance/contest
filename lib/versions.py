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
    #   self._release_separator
    #   self.version
    #   self.release

    def compare(self, other):
        if not isinstance(other, str):
            other = str(other)
        other_version, _, other_release = other.partition(self._release_separator)
        theirs = (None, other_version, other_release if other_release else None)
        # if 'theirs' is without release, omit it for 'ours' too
        # to allow for things like <= '0.1.66'
        ours = (None, self.version, self.release if other_release else None)
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
        self._release_separator = '.'
        v = _os_release['VERSION_ID'].split(self._release_separator)
        if len(v) == 1:
            self.version = v[0]
            self.major = int(v[0])
            self.release = self.minor = None
        else:
            self.version = v[0]
            self.release = v[1]
            self.major = int(v[0])
            self.minor = int(v[1])

    def is_true_rhel(self):
        return _os_release['ID'] == 'rhel'

    def is_centos(self):
        return _os_release['ID'] == 'centos'

    def __bool__(self):
        return _os_release['ID'] in ['rhel', 'centos']


class _Rpm(_RpmVerCmp):
    def __init__(self, name):
        self._release_separator = '-'
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

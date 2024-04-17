import contextlib
import collections
import configparser
import tempfile
import subprocess
import requests
from pathlib import Path

from lib import util, versions

try:
    import dnf
except ModuleNotFoundError as e:
    if versions.rhel != 7:
        raise e from None

_Repo = collections.namedtuple('Repo', ['name', 'baseurl', 'data', 'file'])


# legacy manual parsing due to RHEL-7 having yum
def _get_repos_yum():
    for repofile in Path('/etc/yum.repos.d').iterdir():
        c = configparser.ConfigParser()
        c.read(repofile)
        for section in c.sections():
            # we need at least these to be defined
            if not all(x in c[section] for x in ['name', 'baseurl', 'enabled']):
                continue
            # no disabled repos
            if c[section]['enabled'] != '1':
                continue
            baseurl = c[section]['baseurl']
            # no local-only repos that aren't portable to VM guests
            if baseurl.startswith('file://'):
                continue
            # sanity check for (in)valid URLs as Anaconda fails on broken ones
            elif baseurl.startswith(('http://', 'https://')):
                try:
                    reply = requests.head(baseurl, verify=False, allow_redirects=True)
                    reply.raise_for_status()
                except requests.exceptions.RequestException as e:
                    util.log(f"skipping: {e}")
                    continue
            yield _Repo(name=section, baseurl=baseurl, data=c[section], file=repofile)


# dnf up to dnf4
def _get_repos_dnf():
    db = dnf.Base()
    # black magic to make the dnf python API load /etc/dnf/dnf.conf
    # and variables from /etc/dnf/vars/*, used by CentOS Stream to
    # define $stream, used in metalinks
    # source: https://bugzilla.redhat.com/show_bug.cgi?id=1920735#c2
    db.conf.read(priority=dnf.conf.PRIO_MAINCONFIG)
    db.conf.substitutions.update_from_etc(installroot=db.conf.installroot, varsdir=db.conf.varsdir)
    db.read_all_repos()
    for name, repo in db.repos.items():
        # no disabled repos
        if not repo.enabled:
            continue
        repo.load()
        baseurl = repo.remote_location('/')
        # no local-only repos that aren't portable to VM guests
        if baseurl.startswith('file://'):
            continue
        # sanity check for (in)valid URLs as Anaconda fails on broken ones
        if baseurl.startswith(('http://', 'https://')):
            try:
                reply = requests.head(baseurl, verify=False, allow_redirects=True)
                reply.raise_for_status()
            except requests.exceptions.RequestException as e:
                util.log(f"skipping: {e}")
                continue
        data = dict(repo.cfg.items(name))
        yield _Repo(name=name, baseurl=baseurl, data=data, file=repo.repofile)


# TODO: the dnf4 API will change (confirmed by developers)
def _get_repos_dnf5():
    pass


_repos_cache = None


# cache dnf repository metadata to avoid long delays on repeated retrieval
def _get_repos():
    global _repos_cache
    if _repos_cache is not None:
        return _repos_cache

    if versions.rhel == 7:
        cache = _get_repos_yum()
    else:
        cache = _get_repos_dnf()

    _repos_cache = list(cache)
    return _repos_cache


def repo_configs():
    """
    Yield tuples of (name,dict) of all enabled repositories on the host,
    where 'dict' represents repository .conf contents.
    """
    for repo in _get_repos():
        yield (repo.name, repo.data)


def repo_urls():
    """
    Yield tuples of (name,baseurl) of all enabled repositories on the host.
    """
    for repo in _get_repos():
        yield (repo.name, repo.baseurl)


def repo_files():
    """
    Yield Paths of all enabled repository files (yum.repos.d) on the host.
    """
    # deduplicate paths
    files = set(repo.file for repo in _get_repos())
    yield from files


def installable_url():
    """
    Return one baseurl usable for installing the currently-running system.
    """
    for _, url in repo_urls():
        util.log(f"considering: {url}")
        reply = requests.head(url + '/images/install.img', verify=False)
        if reply.status_code == 200:
            return url
        if versions.rhel == 7:
            reply = requests.head(url + '/LiveOS/squashfs.img', verify=False)
            if reply.status_code == 200:
                return url
    raise RuntimeError("did not find any install-capable repo amongst host repos")


@contextlib.contextmanager
def download_rpm(nvr, source=False):
    """
    Downloads a single RPM by its NVR (which can be just name or any other
    version/release string accepted by DNF) and yields the result as a temporary
    file path.

    'source' specifies whether to download a binary or a source RPM.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        if versions.rhel == 7:
            cmd = ['yumdownloader', '--destdir', tmpdir]
        else:
            cmd = ['dnf', 'download', '--downloaddir', tmpdir]
        if source:
            cmd.append('--source')
        cmd.append(nvr)
        util.subprocess_run(cmd, check=True)
        # unfortunately, these commands mix debug output into stdout, before the
        # printed out NVR of the downloaded package, so just glob it afterwards
        rpmfile = next(Path(tmpdir).glob('*.rpm'))
        yield rpmfile


@contextlib.contextmanager
def extract_rpm(rpmfile):
    """
    Extracts a binary or source RPM using rpm2cpio into a temporary directory,
    yielding a path to that directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        rpm2cpio = util.subprocess_Popen(['rpm2cpio', rpmfile], stdout=subprocess.PIPE)
        cpio_cmd = ['cpio', '-idmv', '--no-absolute-filenames', '-D', tmpdir]
        cpio = util.subprocess_run(cpio_cmd, stdin=rpm2cpio.stdout)
        # safety for when 'cpio' exits before parsing all input,
        # trigger write error for 'rpm2cpio' rather than infinite hang
        rpm2cpio.stdout.close()
        if rpm2cpio.wait() != 0:
            raise RuntimeError(f"rpm2cpio returned non-zero for {rpmfile}")
        if cpio.returncode != 0:
            raise RuntimeError(f"cpio returned non-zero for {rpmfile}")
        yield tmpdir

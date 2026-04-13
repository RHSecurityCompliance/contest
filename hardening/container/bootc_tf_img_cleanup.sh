#!/bin/bash

# note: this script can't be used in the %post scriptlet of the contest-pack RPM
# because when 'dnf install contest-pack.rpm' runs, dnf holds a lock on the RPM
# database for the entire transaction. The %post scriptlet runs within that
# transaction, and it invokes other dnf commands - each would try to acquire
# the same lock. The inner dnf blocks waiting for the lock, the outer dnf blocks
# waiting for the scriptlet to finish and we would get a deadlock.

# set all RHEL repos to gpgcheck=1 and provide a gpgkey= for each of them,
# as RHSM-created repos would have
# - since we can't be sure what GPG key is used for what repo, we simply add
#   all GPG keys to all repos, which works (see dnf documentation)
gpgkeys=()
for key in /etc/pki/rpm-gpg/RPM-GPG-KEY-redhat*; do
    gpgkeys+=("file://$key")
done
sed -i 's/^gpgcheck=0$/gpgcheck=1/' /etc/yum.repos.d/rhel.repo
if ! grep -q '^gpgkey=' /etc/yum.repos.d/rhel.repo; then
    sed -i "/^gpgcheck=1$/a gpgkey=${gpgkeys[*]}" /etc/yum.repos.d/rhel.repo
fi

# verify that main BaseOS repo is reachable, if not update BaseOS, AppStream
# and CRB (repos enabled by default) to point to the latest repos
bos_repo=$(grep '^baseurl=.*/BaseOS/.*/os[/]*$' /etc/yum.repos.d/rhel.repo | sed 's|^.*baseurl=||')
if ! curl -fsSL "${bos_repo%/}/repodata/repomd.xml" > /dev/null; then
    echo "BaseOS repo is not reachable"
    echo "Updating BaseOS, AppStream and CRB to point to the latest repos"

    url=$(grep -o '^.*redhat.com' <<< "$bos_repo")
    app_repo=$(grep '^baseurl=.*/AppStream/.*/os[/]*$' /etc/yum.repos.d/rhel.repo | sed 's|^.*baseurl=||')
    crb_repo=$(grep '^baseurl=.*/CRB/.*/os[/]*$' /etc/yum.repos.d/rhel.repo | sed 's|^.*baseurl=||')

    VERSION_ID=$(grep '^VERSION_ID=' /etc/os-release | cut -d= -f2- | tr -d '"')
    MAJOR_ID=${VERSION_ID%%.*}

    set -x
    sed -i "s|$bos_repo|$url/rhel-$MAJOR_ID/nightly/RHEL-$MAJOR_ID/latest-RHEL-$VERSION_ID/compose/BaseOS/x86_64/os/|" /etc/yum.repos.d/rhel.repo
    sed -i "s|$app_repo|$url/rhel-$MAJOR_ID/nightly/RHEL-$MAJOR_ID/latest-RHEL-$VERSION_ID/compose/AppStream/x86_64/os/|" /etc/yum.repos.d/rhel.repo
    sed -i "s|$crb_repo|$url/rhel-$MAJOR_ID/nightly/RHEL-$MAJOR_ID/latest-RHEL-$VERSION_ID/compose/CRB/x86_64/os/|" /etc/yum.repos.d/rhel.repo
    set +x
fi

# remove non-standard repos and downgrade (if unable to remove)
# or remove the extra non-standard packages from them
rm -v -f /etc/yum.repos.d/{beaker-harness,rcm-tools}.repo
function list_foreign_rpms {
    dnf list --installed \
    | grep -e @epel -e @beaker-harness -e rcm-tools \
    | sed 's/ .*//'
}
rpms=$(list_foreign_rpms)
# shellcheck disable=SC2086 # package list must expand to separate dnf arguments
[[ $rpms ]] && dnf downgrade -y --skip-broken $rpms || true
rpms=$(list_foreign_rpms)
# shellcheck disable=SC2086
[[ $rpms ]] && dnf remove -y --noautoremove $rpms
# downggrade sometimes affects dependencies, so upgrade them back to the latest versions
dnf -y upgrade
dnf clean all

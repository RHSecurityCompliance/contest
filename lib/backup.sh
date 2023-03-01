[[ $_LIB_BACKUP_DEFINED ]] && return
_LIB_BACKUP_DEFINED=1
[[ -z $_LIB_LIBDIR ]] && _LIB_LIBDIR=$(dirname "${BASH_SOURCE[0]}")

#
# These are simple functions for backing up / restoring files and directories,
# incl. SELinux context and other extended attributes.
# Typically used on some /etc/daemon.conf and /etc/daemon.d config dirs.
#

. "$_LIB_LIBDIR/misc.sh"
. "$_LIB_LIBDIR/tmt.sh"
. "$_LIB_LIBDIR/at-exit.sh"

declare -A _lib_backup_files

# backup /etc/file.conf
# backup /etc/cron.d
function backup {
    local bak=$1.tst-bak
    [[ -e $bak ]] && exit_error "backup: $bak exists"
    cp -af "$1" "$bak" || exit_error "backup: failed to copy $1"
    _lib_backup_files[$1]=1
}

# restore a single backed up argument,
# note that restoring removes the backup
# restore /etc/file.conf
function restore {
    if [[ -z ${_lib_backup_files[$1]+exists} ]]; then
        error "backup: $1 was not backed up"
        return 1
    fi
    local bak=$1.tst-bak
    if [[ ! -e $bak ]]; then
        error "backup: $bak does not exist, it was created, but something deleted it"
        return 1
    fi
    unset _lib_backup_files[$1]
    rm -rf "$1" || return 1
    mv -f "$bak" "$1"
}

# restore all backed up arguments, typically on exit
function restore_all {
    local path=
    for path in "${!_lib_backup_files[@]}"; do
        restore "$path" || return 1
    done
}

at_exit restore_all

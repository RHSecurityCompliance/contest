[[ $_SERVICES_DEFINED ]] && return
_SERVICES_DEFINED=1
[[ -z $_LIBDIR ]] && _LIBDIR=$(dirname "${BASH_SOURCE[0]}")

#
# Functions for starting/stoping systemctl services, and restoring them
# to their original state before the start/stop.
#

declare -A _services_orig

function service_start {
    local status=0
    systemctl status "$1" >/dev/null || status=$?
    case "$status" in
        0)
            # already running, no-op
            ;;
        3)
            systemctl start "$1" || return 1
            _services_orig[$1]=stopped
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}

function service_stop {
    local status=0
    systemctl status "$1" >/dev/null || status=$?
    case "$status" in
        0)
            systemctl stop "$1" || return 1
            _services_orig[$1]=started
            ;;
        3)
            # already stopped, no-op
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}

function service_restart {
    local status=0
    systemctl status "$1" >/dev/null || status=$?
    case "$status" in
        0)
            systemctl restart "$1" || return 1
            ;;
        3)
            # restart will also start
            systemctl restart "$1" || return 1
            _services_orig[$1]=stopped
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}

function service_restore {
    local status=0
    systemctl status "$1" >/dev/null || status=$?
    case "$status" in
        0|3) ;;
        *) return 1 ;;
    esac
    case "${_services_orig[$1]}" in
        started)
            [[ $status -eq 0 ]] || systemctl start "$1" || return 1
            unset _services_orig[$1]
            ;;
        stopped)
            [[ $status -eq 3 ]] || systemctl stop "$1" || return 1
            unset _services_orig[$1]
            ;;
        *)
            error "service $1 not previously started/stopped"
            return 1
            ;;
    esac
}

function services_restore {
    local i=
    for i in "${!_services_orig[@]}"; do
        service_restore "$i"
    done
}

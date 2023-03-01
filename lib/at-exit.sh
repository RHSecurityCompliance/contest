[[ $_AT_EXIT_DEFINED ]] && return
_AT_EXIT_DEFINED=1
[[ -z $_LIBDIR ]] && _LIBDIR=$(dirname "${BASH_SOURCE[0]}")

#
# Simple "buffer" of commands to execute on exit, since multiple places using
# 'trap whatever EXIT' would override each other's traps.
# This way, anybody can do 'at_exit whatever' to append a statement to the list
# of commands executed on shell exit.
#

function _at_exit_buffer {
    :
}

function at_exit {
    eval "function _at_exit_buffer {
        $(declare -f _at_exit_buffer | sed '1,2d;$d')
        $*
    }"
}

trap '_at_exit_buffer' EXIT

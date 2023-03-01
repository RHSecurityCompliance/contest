[[ $_LIB_CLEANUP_DEFINED ]] && return
_LIB_CLEANUP_DEFINED=1
[[ -z $_LIB_LIBDIR ]] && _LIB_LIBDIR=$(dirname "${BASH_SOURCE[0]}")

#
# The idea here is to have a "buffer" of cleanup commands, the _cleanup_buffer,
# defined as a function, which is re-defined on each prepend/append.
# At the end, this function is executed to do the clean up.
#

. "$_LIB_LIBDIR/at-exit.sh"

function clear_cleanup {
    function _cleanup_buffer {
        :
    }
}
clear_cleanup

function execute_cleanup {
    _cleanup_buffer
    clear_cleanup
}
# disable e, try to run as much cleanup as possible, despite some commands
# returning non-zero
at_exit "set +e; execute_cleanup"

function append_cleanup {
    eval "function _cleanup_buffer {
        $(declare -f _cleanup_buffer | sed '1,2d;$d')
        $*
    }"
}

function prepend_cleanup {
    eval "function _cleanup_buffer {
        $*
        $(declare -f _cleanup_buffer | sed '1,2d;$d')
    }"
}

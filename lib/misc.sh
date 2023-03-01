[[ $_MISC_DEFINED ]] && return
_MISC_DEFINED=1
[[ -z $_LIBDIR ]] && _LIBDIR=$(dirname "${BASH_SOURCE[0]}")

. "$_LIBDIR/tmt.sh"

# simply print out a msg to stderr, for non-fatal errors
function error {
    printf 'error: %s\n' "$*" >&2
}

# save/restore the xtrace flag, to save on log size in certain tests
function set_x_disable {
    [[ $- = *x* ]] && set_x_disabled=1
    { set +x; } 2>/dev/null
}
function set_x_restore {
    if [ -n "$set_x_disabled" ]; then
        unset set_x_disabled
        { set -x; } 2>/dev/null
    fi
}

# return 0 if the passed first v/r is related to second v/r according to sign
# _rpm_ver_cmp first_v first_r sign second_v second_r
# _rpm_ver_cmp 1.1 1-el9 '<' 1.2 1-el9
# _rpm_ver_cmp 2 '' == 2 ''
function rpm_ver_cmp {
    python3 <<EOF
import sys,rpm
r = rpm.labelCompare((None,'$1','$2'),(None,'$4','$5'))
sys.exit(0 if r $3 0 else 1)
EOF
}

# compare current RHEL version against a sign and a value,
# behave like beakerlib's rlIsRHEL and its sign-based comparison
# isrhel '==8'    # true on 8.0, 8.1, etc.
# isrhel '>7'     # true on any 8, 9, etc.
# isrhel '==8.3'  # true only on 8.3
# isrhel '<=8.3'  # true on 8.3, 8.2, even across majors, 7.9, 6.4, etc.
# isrhel '>7.5'   # true on 7.5, 7.6, any 8, 9, etc.
# isrhel '8'      # equivalent to '==8'
# isrhel '8.3'    # equivalent to '==8.3'
function isrhel {
    local sign=${1%%[0-9]*} tgt=${1##*[><=]}
    [[ -z $sign ]] && sign="=="

    local os_release=$(</etc/os-release)
    local osname=$(eval "$os_release"; echo "$ID")
    [[ $osname == rhel ]] || return 1
    local cur=$(eval "$os_release"; echo "$VERSION_ID")

    local tgt_major=${tgt%%.*} cur_major=${cur%%.*}

    # if target has only major, compare majors
    # else compare the full version
    if [[ $tgt_major == $tgt ]]; then
        rpm_ver_cmp "$cur_major" '' "$sign" "$tgt_major" ''
    else
        rpm_ver_cmp "$cur" '' "$sign" "$tgt" ''
    fi
}

# return 0 if the current system has support for creating virtual machines
function has_virt {
    grep -q -E ' (vmx|svm)' /proc/cpuinfo
}

# verify that a program is reachable in PATH
function assert_in_path {
    # try builtin first
    local path=$(command -v "$1" 2>/dev/null) || true
    # resolve manually if alias (bash cannot do this natively)
    if [[ $path && ${path::1} != / ]]; then
        # avoid crazy Fedora/RH aliases in profile.d
        path=$(/usr/bin/which "$1" 2>/dev/null) || true
    fi
    [[ $path ]] || exit_error "$1 not in PATH"
}
# wait for a child PID and exit the current shell with non-zero
# if the child failed
# first arg: cmdline that failed
# other (optional) args: allowed / expected exit codes
function assert_child_success {
    local msg=$1 code= rc=0
    wait $! || rc=$?
    shift
    if [[ $# -gt 0 ]]; then
        for code in "$@"; do
            [[ $rc -eq $code ]] && return 0
        done
    else
        [[ $rc -eq 0 ]] && return 0
    fi
    exit_error "$msg failed, exitcode: $rc"
}

# compare an installed RPM NVR against the passed version/release,
# fail if the RPM is not installed as well
# isrpm openscap '<=' 1.3.6-3.el8_3  # full v+r
# isrpm openscap '>' 1.3             # partial version
# isrpm openscap                     # just name (installed check)
function isrpm {
    local n=$1 sign=$2 tgt_vr=$3 cur_vr
    cur_vr=$(rpm -q --qf "%{VERSION} %{RELEASE}" "$n") || return 1
    [[ -z $tgt_vr ]] && return 0  # just name, passed exists check
    local tgt_v=${tgt_vr%-*} tgt_r=${tgt_vr##*-} cur_v cur_r
    read -r cur_v cur_r <<<"$cur_vr"
    rpm_ver_cmp "$cur_v" "$cur_r" "$sign" "$tgt_v" "$tgt_r"
}

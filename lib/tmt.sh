[[ $_TMT_DEFINED ]] && return
_TMT_DEFINED=1
[[ -z $_LIBDIR ]] && _LIBDIR=$(dirname "${BASH_SOURCE[0]}")

function _tmt_record_status {
    cat >> "$TMT_TEST_DATA/result.yaml" <<EOF
- name: $1
  result: $2
EOF
}

function exit_error {
    [[ $# -gt 0 ]] && error "error: $1"
    _tmt_record_status / error
    exit 1
}
function exit_fail {
    [[ $# -gt 0 ]] && error "fail: $1"
    _tmt_record_status / fail
    exit 1
}
function exit_pass {
    _tmt_record_status / pass
    exit 0
}

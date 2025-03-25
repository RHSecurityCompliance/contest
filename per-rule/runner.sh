#!/bin/bash

# log everything (stdout + stderr + bash trace) to runner.log
# but keep original stdout and collect it from parent test.py as 'note'
exec 0</dev/null {orig_stdout}>&1 2>runner.log 1>&2

# Exit codes of this script mimic oscap:
#   0 = executing the test script + oscap was according to expectations
#   1 = unknown error occurred
#   2 = test found a potential bug (controlled fail)
function exit_pass { [[ $# -gt 0 ]] && echo -e "$1" >&$orig_stdout; exit 0; }
function exit_err  { [[ $# -gt 0 ]] && echo -e "$1" >&$orig_stdout; exit 1; }
function exit_fail { [[ $# -gt 0 ]] && echo -e "$1" >&$orig_stdout; exit 2; }
function exit_skip { [[ $# -gt 0 ]] && echo -e "$1" >&$orig_stdout; exit 3; }

set -x -e

tests_dir=tests
tests_shared=$tests_dir/shared
variables_dir=variables
playbooks_dir=playbooks
thin_ds_dir=thin_ds

rule=$1             # some_rule_name
test_name=$2        # some_test_name
test_type=$3        # pass or fail
remediation=$4      # oscap or ansible or none
debug_arg=$5        # debug or nodebug

function debug { [[ $debug_arg == debug ]]; }

datastream=$thin_ds_dir/$rule.xml
playbook=$playbooks_dir/$rule.yml
variables_file=$variables_dir/$rule/$test_name.$test_type

# if variables were given, modify datastream/playbook
if [[ -f $variables_file ]]; then
    while IFS='=' read -r key value; do
        # tests may specify variable values either as datastream "selectors"
        # or as raw values - list selector names and check whether the value
        # is amongst them and if so, resolve it
        #
        # we do this loop + retrieval instead of straight retrieval because
        # values can be super crazy and contain quotes, which break @id='...'
        # quote syntax, so we rely on selectors having sensible non-crazy names
        # and when the value == selector, we can probably safely use it inside
        # the @id='...' string
        xccdf_key=xccdf_org.ssgproject.content_value_$key
        # (read with empty -d exits with 1 on EOF, hence the 'true')
        IFS=$'\n' read -r -d '' -a selectors < <(
            xmlstarlet select \
                -t -v "//xccdf-1.2:Value[@id='$xccdf_key']/xccdf-1.2:value/@selector" -n \
                "$datastream"
        ) || true
        for selector in "${selectors[@]}"; do
            if [[ $value == $selector ]]; then
                value=$(
                    xmlstarlet select \
                    -t -v "//xccdf-1.2:Value[@id='$xccdf_key']/xccdf-1.2:value[@selector='$value']" \
                    -n "$datastream"
                )
                break
            fi
        done

        # we need to always change the datastream, even for ansible
        # (because it's used for scanning)
        #
        # <xccdf-1.2:Value id="xccdf_org.ssgproject.content_value_var_something" type="number">
        #  <xccdf-1.2:title>Some title</xccdf-1.2:title>
        #  <xccdf-1.2:description>Some description</xccdf-1.2:description>
        #  <xccdf-1.2:value selector="100MB">100</xccdf-1.2:value>
        #  <xccdf-1.2:value selector="250MB">250</xccdf-1.2:value>
        #  <xccdf-1.2:value selector="500MB">500</xccdf-1.2:value>
        #  <xccdf-1.2:value>100</xccdf-1.2:value>                     <-- we're changing this
        # </xccdf-1.2:Value>
        xmlstarlet edit \
            --inplace \
            --update "//xccdf-1.2:Value[@id='$xccdf_key']/xccdf-1.2:value[not(@selector)]" \
            --value "$value" \
            "$datastream"

        if [[ $remediation == ansible ]]; then
            # - name: Some title
            #   vars:
            #     var_something: '100'
            # use awk instead of sed because key/values may contain quotes
            # and awk allows us to work around that by passing variables via CLI options
            awk -i inplace -v key="$key" -v value="$value" \
                "{ print gensub(\"^([[:space:]]+)\"key\":.*\", \"\\\1\"key\": '\"value\"'\", 1) }" \
                "$playbook"
        fi
    done < "$variables_file"
fi

if debug; then
    ln "$datastream" ds.xml
    [[ $remediation == ansible ]] && ln "$playbook" playbook.yml
fi

rule_full=xccdf_org.ssgproject.content_rule_$rule

# do a scan prior to running the test script
if debug; then
    rc=0
    out=$(
        oscap xccdf eval --profile '(all)' --rule "$rule_full" --progress \
        --report initial-report.html --results-arf initial-results-arf.xml \
        "$datastream"
    ) || rc=$?
    if [[ $rc != 0 && $rc != 2 ]]; then
        exit_err "oscap exited unexpectedly with $rc"
    fi
fi

# run test script
test_cwd=$tests_dir/$rule
test_file=$test_name.$test_type.sh
rc=0
(
    # we need to call $SHELL because some tests don't start with shebang
    export SHARED=$(realpath "$tests_shared") && \
    cd "$test_cwd" && \
    exec "$SHELL" -x "$test_file"
) &> test.log || rc=$?
if [[ $rc != 0 ]]; then
    exit_err "test script failed with $rc"
fi
debug && cp --reflink=always "$test_cwd/$test_file" "test.$test_type.sh"

# reminder:
#   'something.pass.sh' = test prepares OS, oscap scan should pass
#   'something.fail.sh' = test breaks OS, oscap should remediate + pass
#   'something.fail.sh' with remediation=none = test breaks OS, oscap should fail

if debug; then
    oscap_reports=(--report report.html --results-arf results-arf.xml)
else
    oscap_report=()
fi

# just do an oscap scan, expect it to pass
if [[ $test_type == pass ]]; then
    rc=0
    out=$(
        oscap xccdf eval --profile '(all)' --rule "$rule_full" \
        --progress "${oscap_reports[@]}" "$datastream"
    ) || rc=$?
    if [[ $rc != 0 && $rc != 2 ]]; then
        exit_err "oscap exited unexpectedly with $rc"
    fi

    IFS=: read -r oscap_rule oscap_status <<<"$out"
    if [[ $oscap_rule != $rule_full ]]; then
        exit_err "oscap returned malformed output:\n$out"
    elif [[ $oscap_status == notapplicable ]]; then
        exit_skip
    elif [[ $oscap_status != pass ]]; then
        exit_fail "oscap scan returned $oscap_status, expected 'pass'"
    fi

    exit_pass

elif [[ $test_type == fail ]]; then
    # just do an oscap scan, expect it to fail
    if [[ $remediation == none ]]; then
        rc=0
        out=$(
            oscap xccdf eval --profile '(all)' --rule "$rule_full" \
            --progress "${oscap_reports[@]}" "$datastream"
        ) || rc=$?

        if [[ $rc != 0 && $rc != 2 ]]; then
            exit_err "oscap exited unexpectedly with $rc"
        fi

        IFS=: read -r oscap_rule oscap_status <<<"$out"
        if [[ $oscap_rule != $rule_full ]]; then
            exit_err "oscap returned malformed output:\n$out"
        elif [[ $oscap_status == notapplicable ]]; then
            exit_skip
        elif [[ $oscap_status != fail ]]; then
            exit_fail "oscap scan returned $oscap_status, expected 'fail'"
        fi

        exit_pass

    # remediate+scap using oscap, expect it to pass
    elif [[ $remediation == oscap ]]; then
        rc=0
        out=$(
            oscap xccdf eval --profile '(all)' --rule "$rule_full" --remediate \
            --progress "${oscap_reports[@]}" "$datastream"
        ) || rc=$?

        if [[ $rc != 0 && $rc != 2 ]]; then
            exit_err "oscap exited unexpectedly with $rc"
        fi

        # read all oscap output, as lines, into bash array
        # (read with empty -d exits with 1 on EOF, hence the 'true')
        IFS=$'\n' read -r -d '' -a lines <<<"$out" || true
        if [[ ${#lines[@]} -eq 0 ]]; then
            exit_err "oscap returned malformed output:\n$out"
        fi

        # first line: fail
        IFS=: read -r oscap_rule oscap_status <<<"${lines[0]}"
        if [[ $oscap_rule != $rule_full ]]; then
            exit_err "oscap returned malformed output on first line:\n$out"
        elif [[ $oscap_status == notapplicable ]]; then
            exit_skip
        elif [[ $oscap_status != fail ]]; then
            exit_fail "oscap initial scan returned $oscap_status, expected 'fail'"
        fi

        if [[ ${#lines[@]} -ne 2 ]]; then
            exit_err "oscap did not output 2 lines (fail+fixed):\n$out"
        fi

        # second line: fixed
        IFS=: read -r oscap_rule oscap_status <<<"${lines[1]}"
        if [[ $oscap_rule != $rule_full ]]; then
            exit_err "oscap returned malformed output on second line:\n$out"
        elif [[ $oscap_status != fixed ]]; then
            exit_fail "oscap fixing returned $oscap_status, expected 'fixed'"
        fi

        exit_pass

    # remediate via ansible-playbook + scan via oscap, expect it to pass
    elif [[ $remediation == ansible ]]; then
        rc=0
        out=$(
            ansible-playbook -v -c local -i 127.0.0.1, "$playbook"
        ) || rc=$?

        if [[ $rc != 0 ]]; then
            exit_err "ansible-playbook exited unexpectedly with $rc"
        fi

        rc=0
        out=$(
            oscap xccdf eval --profile '(all)' --rule "$rule_full" \
            --progress "${oscap_reports[@]}" "$datastream"
        ) || rc=$?

        if [[ $rc != 0 && $rc != 2 ]]; then
            exit_err "oscap exited unexpectedly with $rc"
        fi

        IFS=: read -r oscap_rule oscap_status <<<"$out"
        if [[ $oscap_rule != $rule_full ]]; then
            exit_err "oscap returned malformed output:\n$out"
        elif [[ $oscap_status == notapplicable ]]; then
            exit_skip
        elif [[ $oscap_status != pass ]]; then
            exit_fail "oscap scan returned $oscap_status, expected 'pass'"
        fi

        exit_pass

    else
        exit_err "unknown remediation type: $remediation"
    fi
else
    exit_err "wrong test_type: $test_type"
fi

exit_err "reached the end of runner (bug)"

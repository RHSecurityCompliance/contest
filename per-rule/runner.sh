#!/bin/bash

exec {BASH_XTRACEFD}>runner.log
set -x

# Exit codes of this script mimic oscap:
#   0 = executing the test script + oscap was according to expectations
#   1 = unknown error occurred
#   2 = test found a potential bug (controlled fail)
function exit_pass { [[ $# -gt 0 ]] && echo -e "$1" >&2; exit 0; }
function exit_err  { [[ $# -gt 0 ]] && echo -e "$1" >&2; exit 1; }
function exit_fail { [[ $# -gt 0 ]] && echo -e "$1" >&2; exit 2; }

set -e

tests_dir=tests
playbooks_dir=playbooks
thin_ds_dir=thin_ds

rule=$1             # some_rule_name
test_name=$2        # some_test_name
test_type=$3        # pass or fail
remediation=$4      # oscap or ansible or none
variables="${@:5}"  # key=value key2=value2 ...

playbook="$playbooks_dir/$rule.yml"
datastream="$thin_ds_dir/$rule.xml"

# if variables were given, modify datastream/playbook
if [[ ${#variables[@]} -gt 0 ]]; then
    if [[ $remediation == oscap ]]; then
        for var in "${variables[@]}"; do
            IFS='=' read key value <<<"$var"
            key="xccdf_org.ssgproject.content_value_$key"
            # <xccdf-1.2:Value id="xccdf_org.ssgproject.content_value_var_something" type="number">
            #  <xccdf-1.2:title>Some title</xccdf-1.2:title>
            #  <xccdf-1.2:description>Some description</xccdf-1.2:description>
            #  <xccdf-1.2:value selector="100MB">100</xccdf-1.2:value>
            #  <xccdf-1.2:value selector="250MB">250</xccdf-1.2:value>
            #  <xccdf-1.2:value selector="500MB">500</xccdf-1.2:value>
            #  <xccdf-1.2:value>100</xccdf-1.2:value>                     <-- we're changing this
            # </xccdf-1.2:Value>
            xmlstarlet ed \
                --update "//xccdf-1.2:Value[@id='$key']/xccdf-1.2:value[not(@selector)]" \
                --value "$value" \
                --inplace \
                "$datastream"
        done
    elif [[ $remediation == ansible ]]; then
        sed_args=()
        for var in "${variables[@]}"; do
            IFS='=' read key value <<<"$var"
            # - name: Some title
            #   vars:
            #     var_something: '100'
            sed_args+=(-e "/[[:space:]]$key:/s/:.*/: '$value'/")
        done
        sed "${sed_args[@]}" -i "$playbook"
    fi
fi

rule_full="xccdf_org.ssgproject.content_rule_$rule"
test_cwd="$tests_dir/$rule"
test_file="$test_name.$test_type.sh"

# reminder:
#   'something.pass.sh' = test prepares OS, oscap scan should pass
#   'something.fail.sh' = test breaks OS, oscap should remediate + pass
#   'something.fail.sh' with remediation=none = test breaks OS, oscap should fail

# run the test script + oscap scan/remediation
if [[ $test_type == pass ]]; then
    if ! (cd "$test_cwd" && "$SHELL" "$test_file" &> test.log); then
        exit_err "test script failed with $?"
    fi

    rc=0
    out=$(
        oscap xccdf eval --profile '(all)' --rule "$rule_full"
        --progress "$datastream"
    ) || rc=$?

    case $rc in
        0)
            IFS=: read oscap_rule oscap_status <<<"$out"
            if [[ $oscap_rule != $rule_full || $oscap_status != pass ]]; then
                exit_err "oscap returned 0, but got malformed output:\n$out"
            fi

            exit_pass
            ;;

        2)
            # valid fail, re-do scan with full reports (slower)
            out=$(
                oscap xccdf eval --profile '(all)' --rule "$rule_full"
                --progress --results-arf results-arf.xml "$datastream"
            ) || rc=$?

            IFS=: read oscap_rule oscap_status <<<"$out"
            if [[ $rc != 2 ]]; then
                exit_err "oscap found fail, but scan rerun succeeded"
            elif [[ $oscap_rule != $rule_full || $oscap_status != fail ]]; then
                exit_err "oscap found fail, but got malformed output:\n$out"
            fi

            exit_fail "oscap found failure"
            ;;

        \?)
            exit_err "oscap exited unexpectedly with $rc"
    esac

elif [[ $test_type == fail ]]; then
    if ! (cd "$test_cwd" && "$SHELL" "$test_file" &> test.log); then
        exit_err "test script failed with $?"
    fi


    # TODO: if [[ $remediation == none ]]

    rc=0
    out=$(
        oscap xccdf eval --profile '(all)' --rule "$rule_full" --remediate
        --progress --results-arf results-arf.xml "$datastream"
    ) || rc=$?

    if [[ $rc == 0 ]]; then
        exit_fail "test script probably broken, oscap returned 0"
    elif [[ $rc != 2 ]]; then
        exit_err "oscap exited unexpectedly with $rc"
    fi

    IFS=$'\n' read -d '' -a lines <<<"$out"
    if [[ ${#lines[@]} -ne 2 ]]; then
        exit_err "oscap did not output 2 lines (fail+fixed):\n$out"
    fi

    IFS=: read oscap_rule oscap_status <<<"${lines[0]}"
    if [[ $oscap_rule != $rule_full || $oscap_status != fail ]]; then
        exit_err "oscap got non-fail output (first line):\n$out"
    fi

    IFS=: read oscap_rule oscap_status <<<"${lines[1]}"
    if [[ $oscap_rule != $rule_full ]]; then
        exit_err "oscap got malformed output (second line):\n$out"
    elif [[ $oscap_status != fixed ]]; then
        exit_fail "oscap failed to fix the problem, scan returned: $oscap_status"
    fi

    exit_pass

else
    exit_err "wrong test_type: $test_type"
fi

exit_err "reached the end of runner (bug)"

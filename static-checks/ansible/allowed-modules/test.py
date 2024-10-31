#!/usr/bin/python3

import re
import tempfile
import subprocess
import yaml
import json
import contextlib
from pathlib import Path

from lib import util, results, ansible


# Obtained from
# https://docs.ansible.com/ansible/latest/reference_appendices/playbooks_keywords.html#task
ansible_reserved_keywords = {
    'action', 'any_errors_fatal', 'args', 'async', 'become', 'become_exe', 'become_flags',
    'become_method', 'become_user', 'changed_when', 'check_mode', 'collections', 'connection',
    'debugger', 'delay', 'delegate_facts', 'delegate_to', 'diff', 'environment', 'failed_when',
    'ignore_errors', 'ignore_unreachable', 'local_action', 'loop', 'loop_control',
    'module_defaults', 'name', 'no_log', 'notify', 'poll', 'port', 'register', 'remote_user',
    'retries', 'run_once', 'tags', 'throttle', 'timeout', 'until', 'vars', 'when', 'with_items'
}


@contextlib.contextmanager
def select_all_rules(datastream):
    """
    Given an XML file path as 'datastream' enable all the rules in the datastream.

    Use as a context manager, returning a filesystem path to the
    modified datastream.
    """
    exprs = set()
    exprs.add(re.compile(r'<.*Rule.*id="'))
    exprs.add(re.compile(r'<.*select.*idref="'))

    with open(datastream) as ds:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml') as new_ds:
            for line in ds:
                if any(x.search(line) for x in exprs):
                    line = line.replace('selected="false"', 'selected="true"')
                new_ds.write(line)
            new_ds.flush()
            util.log(f"Saving modified {datastream} with all rules selected as {new_ds.name}")
            yield Path(new_ds.name)


def process_task(task, all_allowed_modules):
    original_keywords = set(task.keys())
    found_allowed_modules = set()

    if 'block' in original_keywords:
        for block_task in task['block']:
            found_allowed_modules.update(process_task(block_task, all_allowed_modules))
    else:
        keywords = set(kw.replace('ansible.builtin.', '') for kw in original_keywords)
        keywords = set(kw.replace('community.general.', '') for kw in keywords)
        keywords = set(kw.replace('ansible.posix.', '') for kw in keywords)
        allowed_module = keywords.intersection(all_allowed_modules)
        if allowed_module:
            found_allowed_modules.update(allowed_module)
        else:
            # No allowed module found in 'keywords' means there is a module
            # which is forbidden and we obtain it by filtering out all the
            # reserved keywords for Ansible tasks which will leave us with
            # one item and that should be the name of that forbidden module.
            forbidden_module = keywords.difference(ansible_reserved_keywords).pop()
            task_name = task['name'] if 'name' in task else ''
            results.report('fail', forbidden_module, f'task: \'{task_name}\'')

    return found_allowed_modules


def check_allowed_modules(playbook, all_allowed_modules):
    """
    Collects all modules from Ansible playbook playbook_path and reports pass
    if a module is found in the allowed_modules set, otherwise reports fail
    and prints an offending Ansible module and task. Function also handles
    Ansible block sections which can bundle multiple tasks.
    Note: ansible playbook must be a valid playbook which means that
    'ansible-playbook --syntax-check' must not report any errors for it.
    """
    found_allowed_modules = set()

    util.log(f"Check Ansible playbook {playbook.name} contains only allowed modules")
    for section in yaml.safe_load(playbook):
        for task in section['tasks']:
            found_allowed_modules.update(process_task(task, all_allowed_modules))

    for module in sorted(found_allowed_modules):
        results.report('pass', module)


def get_all_allowed_modules():
    proc = util.subprocess_run(
        ['ansible-doc', '--json', '--list'], stdout=subprocess.PIPE, check=True
    )
    return set(re.sub(r'^.*\.', '', mod) for mod in json.loads(proc.stdout).keys())


ansible.install_deps()

with select_all_rules(util.get_datastream()) as ds_file:
    with open(ds_file) as ds:
        with tempfile.NamedTemporaryFile(suffix='.yml') as playbook:
            util.log(f"Generate Ansible playbook {playbook.name} for all rules from {ds_file}")
            oscap_cmd = [
                'oscap', 'xccdf', 'generate', 'fix', '--fix-type', 'ansible',
                '--output', playbook.name,
                ds.name
            ]
            util.subprocess_run(oscap_cmd, check=True)

            util.subprocess_run(['ansible-playbook', '--syntax-check', playbook.name], check=True)

            check_allowed_modules(playbook, get_all_allowed_modules())

results.report_and_exit()

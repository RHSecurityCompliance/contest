import os
import subprocess
import sys
import tempfile
from pathlib import Path

from lib import ansible, results, util

playbooks = sorted(util.iter_per_rule_playbooks())

# slice playbooks, get every total-th member
start = int(util.get_test_name().rpartition("/")[2]) - 1
total = int(os.environ["TOTAL_SLICES"])
playbooks = playbooks[start::total]
if not playbooks:
    results.report_and_exit("skip", note="no per-rule playbooks in this slice")

util.log(f"will be linting {len(playbooks)} per-rule playbooks")

ansible.install_deps()

# keep pip's ansible-core inside a venv, so its commands don't shadow
# the system RPM in later tests; use CONTEST_PYTHON, not the older system Python
with tempfile.TemporaryDirectory() as venv_dir:
    util.subprocess_run([sys.executable, "-m", "venv", venv_dir], check=True)
    venv_python = Path(venv_dir) / "bin" / "python"
    util.subprocess_run(
        [venv_python, "-m", "pip", "install", "ansible-lint"],
        check=True,
    )

    for playbook in playbooks:
        cmd = [
            venv_python, "-m", "ansiblelint", "--offline", "--nocolor", "--profile", "min",
            playbook,
        ]
        # ansible-lint writes violations to stdout
        ret = util.subprocess_run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if ret.returncode == 0:
            results.report("pass", playbook.name)
        else:
            results.report("fail", playbook.name, ret.stdout)

results.report_and_exit()

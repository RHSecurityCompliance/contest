import subprocess
import sys
import tempfile
from pathlib import Path

from lib import ansible, results, util


def lint_playbook(playbook, name):
    cmd = [
        venv_python, "-m", "ansiblelint",
        "--offline", "--nocolor", "--profile", "min",
        playbook,
    ]
    # ansible-lint writes violations to stdout
    ret = util.subprocess_run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if ret.returncode == 0:
        results.report("pass", name)
    else:
        results.report("fail", name, ret.stdout)


ansible.install_deps()

ds = util.get_datastream()

# Install ansible-lint in an isolated venv - installing it via pip directly
# would also install its ansible-core dependency, whose console scripts
# (e.g. ansible-playbook) in /usr/local/bin would then shadow the system
# ansible-core RPM in all tests that run afterwards, breaking e.g.
# /hardening/ansible on RHEL-8, whose guests only have Python 3.6.
# The venv is created with sys.executable (CONTEST_PYTHON), not bare pip3,
# because on RHEL-8/9 pip3 targets the older system Python and cannot
# provide a modern ansible-lint.
with tempfile.TemporaryDirectory() as venv_dir:
    util.subprocess_run([sys.executable, "-m", "venv", venv_dir], check=True)
    venv_python = Path(venv_dir) / "bin" / "python"
    util.subprocess_run(
        [venv_python, "-m", "pip", "install", "ansible-lint"],
        check=True,
    )

    # lint generated playbook with virtual (all) profile
    cmd = [
        "oscap", "xccdf", "generate", "fix", "--profile", "(all)",
        "--fix-type", "ansible", "--output", "playbook.yml", ds,
    ]
    util.subprocess_run(cmd, check=True, stderr=subprocess.PIPE)
    lint_playbook("playbook.yml", "(all) profile generated")

    # lint shipped playbooks
    for playbook in util.iter_playbooks():
        lint_playbook(playbook, playbook.name)

    # lint per-rule playbooks
    for playbook in util.iter_per_rule_playbooks():
        lint_playbook(playbook, playbook.name)

results.report_and_exit()

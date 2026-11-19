import re
from pathlib import Path

from lib import util, versions


def fips_allow_ssh_ed25519():
    """Allow ed25519 SSH auth after FIPS policy changes and a reboot."""
    if versions.rhel == 8:
        name = "PubkeyAcceptedKeyTypes"
        regex = fr"CRYPTO_POLICY=.*-o{name}=([^\s'\"]+)"
    else:
        name = "PubkeyAcceptedAlgorithms"
        regex = fr"{name}\s+(\S+)"

    with open("/etc/crypto-policies/back-ends/opensshserver.config") as policy:
        for line in policy:
            if match := re.match(regex, line.strip()):
                break
        else:
            raise RuntimeError(f"{name} not found in SSH crypto policy")

    algorithms = match.group(1)
    algorithms += ",ssh-ed25519"

    environment = Path("/etc/sysconfig/sshd-ed25519")
    environment.write_text(f'OPTIONS="-o{name}={algorithms}"\n')

    # inject EnvironmentFile that overrides $OPTIONS
    override = Path("/etc/systemd/system/sshd.service.d/05-allow-ed25519.conf")
    util.log(f"allowing ed25519 SSH auth via {override}")
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text(f"[Service]\nEnvironmentFile={environment}\n")

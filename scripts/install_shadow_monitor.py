#!/usr/bin/env python3
"""Install a local systemd user timer for shadow reports, with no external messaging."""

from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UNIT = "quant-longterm-shadow"


def quoted(path: Path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def service_contents(root: Path) -> str:
    """WorkingDirectory is a path directive, not a shell-quoted command argument."""
    if not root.is_absolute() or any(c in str(root) for c in "\r\n"):
        raise ValueError("systemd requires an absolute project path without line breaks")
    return f"""# Managed by my_quant_project/scripts/install_shadow_monitor.py
[Unit]
Description=Quant long-term shadow data and signal evaluation

[Service]
Type=oneshot
WorkingDirectory={str(root).replace("%", "%%")}
ExecStart={quoted(root / "scripts/quant")} platform daily --refresh-public --update-tdx
Environment=PYTHONUNBUFFERED=1
TimeoutStartSec=20min
UMask=0077
"""


def main() -> None:
    destination = Path.home() / ".config/systemd/user"
    destination.mkdir(parents=True, exist_ok=True)
    service = service_contents(ROOT)
    timer = f"""# Managed by my_quant_project/scripts/install_shadow_monitor.py
[Unit]
Description=Daily CN and US completed-session shadow evaluation

[Timer]
OnCalendar=*-*-* 00:30:00 UTC
OnCalendar=*-*-* 09:30:00 UTC
Persistent=true
RandomizedDelaySec=120
Unit={UNIT}.service

[Install]
WantedBy=timers.target
"""
    units = (("service", service), ("timer", timer))
    for extension, _ in units:
        target = destination / f"{UNIT}.{extension}"
        if target.exists() and not target.read_text().startswith("# Managed by my_quant_project/"):
            raise RuntimeError(f"refusing to overwrite an unmanaged unit: {target}")
    with tempfile.TemporaryDirectory(prefix="quant-systemd-verify-") as temporary:
        candidates = []
        for extension, contents in units:
            candidate = Path(temporary) / f"{UNIT}.{extension}"
            candidate.write_text(contents, encoding="utf-8")
            candidates.append(str(candidate))
        subprocess.run(["systemd-analyze", "--user", "verify", *candidates], check=True)
    for extension, contents in units:
        target = destination / f"{UNIT}.{extension}"
        target.write_text(contents, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"], check=True)
    subprocess.run(
        ["systemctl", "--user", "list-timers", f"{UNIT}.timer", "--no-pager"], check=True
    )


if __name__ == "__main__":
    main()

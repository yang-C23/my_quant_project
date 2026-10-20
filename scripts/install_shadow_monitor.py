#!/usr/bin/env python3
"""Install a local systemd user timer for shadow reports, with no external messaging."""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UNIT = "quant-longterm-shadow"


def quoted(path: Path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def main() -> None:
    destination = Path.home() / ".config/systemd/user"
    destination.mkdir(parents=True, exist_ok=True)
    service = f"""# Managed by my_quant_project/scripts/install_shadow_monitor.py
[Unit]
Description=Quant long-term shadow data and signal evaluation

[Service]
Type=oneshot
WorkingDirectory={quoted(ROOT)}
ExecStart={quoted(ROOT / "scripts/quant")} platform daily --refresh-public --update-tdx
Environment=PYTHONUNBUFFERED=1
TimeoutStartSec=20min
UMask=0077
"""
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
    for extension, contents in (("service", service), ("timer", timer)):
        target = destination / f"{UNIT}.{extension}"
        if target.exists() and not target.read_text().startswith("# Managed by my_quant_project/"):
            raise RuntimeError(f"refusing to overwrite an unmanaged unit: {target}")
        target.write_text(contents, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"], check=True)
    subprocess.run(
        ["systemctl", "--user", "list-timers", f"{UNIT}.timer", "--no-pager"], check=True
    )


if __name__ == "__main__":
    main()

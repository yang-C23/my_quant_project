#!/usr/bin/env python3
"""Install the repository skill for Codex and update existing local editor copies."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from quant.config import get_settings


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / "skills" / "quant-analyst-myproj"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    audit = get_settings().data_root / "audits" / "skill-sync" / stamp
    audit.mkdir(parents=True)
    codex = Path.home() / ".codex" / "skills" / source.name
    codex.parent.mkdir(parents=True, exist_ok=True)
    if codex.is_symlink() and codex.resolve() != source.resolve():
        raise ValueError("existing Codex skill points elsewhere; preserve it")
    if not codex.exists() and not codex.is_symlink():
        codex.symlink_to(source, target_is_directory=True)
    copies = [codex]
    for prefix in (Path.home() / ".config/opencode/skills", Path.home() / ".cursor/skills"):
        target = prefix / source.name
        if target.exists():
            copies.append(target)
    records = []
    for target in copies:
        for relative in (Path("SKILL.md"), Path("agents/openai.yaml")):
            src, dst = source / relative, target / relative
            if dst.exists() and dst.resolve() == src.resolve():
                pass
            else:
                if dst.exists() and dst.read_bytes() != src.read_bytes():
                    saved = audit / hashlib.sha256(str(target).encode()).hexdigest()[:12] / relative
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst, saved)
                    saved.chmod(0o600)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            assert src.read_bytes() == dst.read_bytes()
            records.append(
                {"path": str(dst), "sha256": hashlib.sha256(dst.read_bytes()).hexdigest()}
            )
    report = {"source": str(source), "installed": records, "previous_copies_preserved": str(audit)}
    (audit / "sync.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

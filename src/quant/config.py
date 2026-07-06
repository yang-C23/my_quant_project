from __future__ import annotations

import json
from pathlib import Path

import yaml


def load_config(config_path: str | Path) -> dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    suffix = path.suffix.lower()
    content = path.read_text(encoding="utf-8")

    if suffix in {".yml", ".yaml"}:
        data = yaml.safe_load(content) or {}
    elif suffix == ".json":
        data = json.loads(content) if content.strip() else {}
    else:
        raise ValueError("Config must be .yaml, .yml, or .json")

    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping object")
    return data

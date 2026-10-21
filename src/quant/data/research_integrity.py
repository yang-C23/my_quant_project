"""Verify stored experiment bytes as well as their replay manifests."""

import json
from pathlib import Path

from quant.data.snapshots import sha256_file


def verify_research_replay(original: Path, replay: Path) -> dict:
    """Require nonempty identical inventories, intact files and the same registered code."""
    manifests, invalid = [], []
    for label, directory in (("original", original), ("replay", replay)):
        inventory = json.loads((directory / "payloads.json").read_text())
        if not inventory:
            raise ValueError("empty replay inventory is not evidence")
        manifests.append(inventory)
        for relative, expected in inventory.items():
            path = directory / relative
            if not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError("payload outside the registered experiment")
            if not path.is_file() or sha256_file(path) != expected:
                invalid.append({"run": label, "payload": relative})
    changed = sorted(
        name
        for name in set(manifests[0]) | set(manifests[1])
        if manifests[0].get(name) != manifests[1].get(name)
    )
    codes = [
        json.loads((directory / "registration.json").read_text()).get("code", {}).get("sources")
        for directory in (original, replay)
    ]
    same_code = bool(codes[0]) and codes[0] == codes[1]
    return {
        "original": str(original),
        "replay": str(replay),
        "ok": not invalid and not changed and same_code,
        "payloads": len(manifests[0]),
        "actual_files_checked": sum(len(manifest) for manifest in manifests),
        "changed_payloads": changed,
        "invalid_files": invalid,
        "same_registered_source_bytes": same_code,
        "registered_source_bytes_present": all(code is not None for code in codes),
        "scope": "byte_integrity_and_reproduction_not_financial_validity_or_PIT_admission",
    }

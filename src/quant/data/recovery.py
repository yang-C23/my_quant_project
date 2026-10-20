"""Offline snapshot backup and isolated restore drills with integrity verification."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

from quant.data.snapshots import SnapshotStore, sha256_file, utc_now, write_json


def backup_snapshot(data_root: Path, snapshot_id: str) -> dict:
    """Create a non-destructive local TAR backup after checking every source file."""
    store = SnapshotStore(data_root)
    checked = store.verify(snapshot_id)
    if not checked["ok"]:
        raise ValueError("cannot back up a corrupted snapshot")
    directory = data_root / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{snapshot_id}.tar"
    if target.exists():
        receipt_path = target.with_suffix(".json")
        if not receipt_path.exists():
            raise ValueError("backup exists without an integrity receipt")
        receipt = json.loads(receipt_path.read_text())
        if sha256_file(target) != receipt["archive_sha256"]:
            raise ValueError("existing backup checksum differs")
        return receipt
    temporary = target.with_suffix(".tar.part")
    try:
        with tarfile.open(temporary, "w") as archive:
            archive.add(store.path(snapshot_id), arcname=snapshot_id, recursive=True)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = {
        "snapshot_id": snapshot_id,
        "created_at": utc_now(),
        "archive": str(target),
        "archive_sha256": sha256_file(target),
        "bytes": target.stat().st_size,
        "scope": "same_machine_backup_not_offsite_disaster_recovery",
    }
    write_json(target.with_suffix(".json"), receipt)
    return receipt


def restore_drill(data_root: Path, snapshot_id: str) -> dict:
    """Restore into a temporary isolated store; never switch the live snapshot."""
    store = SnapshotStore(data_root)
    archive_path = data_root / "backups" / f"{snapshot_id}.tar"
    receipt = json.loads(archive_path.with_suffix(".json").read_text())
    if sha256_file(archive_path) != receipt["archive_sha256"]:
        raise ValueError("archive checksum failed")
    root = data_root / "recovery_drills"
    root.mkdir(parents=True, exist_ok=True)
    active_before = store.current()
    with tempfile.TemporaryDirectory(prefix="restore-", dir=root) as temporary:
        recovery = SnapshotStore(Path(temporary))
        recovery.root.mkdir(parents=True)
        with tarfile.open(archive_path, "r") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or not path.parts
                    or path.parts[0] != snapshot_id
                ):
                    raise ValueError("unsafe archive path")
                if not member.isdir() and not member.isfile():
                    raise ValueError("links/devices are not permitted in data backups")
            archive.extractall(recovery.root)
        integrity = recovery.verify(snapshot_id)
        if not integrity["ok"]:
            raise ValueError("restored snapshot failed verification")
        recovery.activate(snapshot_id)
        if recovery.current() != snapshot_id:
            raise ValueError("isolated pointer replay failed")
        recovery.activate("legacy")
        if recovery.current() is not None:
            raise ValueError("isolated rollback failed")
        recovery.activate(snapshot_id)
    if store.current() != active_before:
        raise RuntimeError("live pointer changed during restore drill")
    report = {
        "snapshot_id": snapshot_id,
        "completed_at": utc_now(),
        "integrity": integrity,
        "isolated_publish_and_rollback": True,
        "live_snapshot_unchanged": True,
        "scope": "full_local_backup_restore_not_offsite_recovery",
    }
    write_json(root / f"{snapshot_id}.json", report)
    return report

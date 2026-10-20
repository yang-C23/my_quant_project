"""Immutable data manifests and an atomic active-snapshot pointer."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Iterator
import uuid

_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def utc_now() -> str:
    """Return an unambiguous UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    """Hash a file in bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    """Atomically replace a JSON document; reject nonstandard NaN values."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def assert_unsealed(target: Path) -> None:
    """Guard legacy writer APIs against modifying any sealed snapshot descendant."""
    target = target.resolve()
    for directory in (target, *target.parents):
        marker = directory / "manifest.json"
        if marker.exists():
            metadata = json.loads(marker.read_text())
            if "snapshot_id" in metadata:
                raise ValueError("sealed snapshot is immutable; build a new snapshot")


def tree_manifest(root: Path) -> list[dict]:
    """Inventory payloads, excluding this store's own mutable control files."""
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.relative_to(root).as_posix() not in {"manifest.json", "progress.json"}
    ]


class SnapshotStore:
    """Publish completed snapshots without overwriting the legacy data tree."""

    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)
        self.root = self.data_root / "snapshots"
        self.pointer = self.data_root / "current.json"

    def path(self, snapshot_id: str) -> Path:
        """Resolve a validated identifier, never an arbitrary relative path."""
        if not _ID.fullmatch(snapshot_id):
            raise ValueError("invalid snapshot_id")
        return self.root / snapshot_id

    def current(self) -> str | None:
        """Return the pinned active identifier; None denotes legacy storage."""
        if not self.pointer.exists():
            return None
        value = json.loads(self.pointer.read_text())["snapshot_id"]
        if value == "legacy":
            return None
        self.path(value)
        return value

    @contextmanager
    def writer_lock(self) -> Iterator[None]:
        """Allow one data publisher at a time; do not wait silently."""
        self.data_root.mkdir(parents=True, exist_ok=True)
        with (self.data_root / ".publisher.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("another data publisher is running") from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def create(self) -> tuple[str, Path]:
        """Allocate an unpublished build directory."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot_id = f"{stamp}-{uuid.uuid4().hex[:10]}"
        directory = self.path(snapshot_id)
        directory.mkdir(parents=True)
        return snapshot_id, directory

    def seal(self, snapshot_id: str, metadata: dict) -> dict:
        """Freeze a completed build and its lineage into a manifest."""
        directory = self.path(snapshot_id)
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            raise FileExistsError("a sealed snapshot cannot be rewritten")
        manifest = {
            **metadata,
            "snapshot_id": snapshot_id,
            "schema_version": 1,
            "created_at": utc_now(),
            "files": tree_manifest(directory),
        }
        write_json(manifest_path, manifest)
        return manifest

    def verify(self, snapshot_id: str) -> dict:
        """Verify contents and detect missing, altered, or extra payload files."""
        directory = self.path(snapshot_id)
        manifest = json.loads((directory / "manifest.json").read_text())
        expected = {row["path"]: row for row in manifest["files"]}
        actual = {row["path"]: row for row in tree_manifest(directory)}
        errors = [
            key
            for key in sorted(expected.keys() | actual.keys())
            if expected.get(key) != actual.get(key)
        ]
        return {"snapshot_id": snapshot_id, "ok": not errors, "changed_files": errors}

    def activate(self, snapshot_id: str) -> None:
        """Atomically select verified data, or explicitly restore legacy storage."""
        previous = self.current()
        if snapshot_id != "legacy":
            manifest = json.loads((self.path(snapshot_id) / "manifest.json").read_text())
            if manifest.get("qlib_built") is False:
                raise ValueError("snapshot lacks the required Qlib compatibility cache")
            if manifest.get("publication_status") != "validated":
                raise ValueError("snapshot has not passed publication validation")
            if not self.verify(snapshot_id)["ok"]:
                raise ValueError("snapshot integrity check failed")
        write_json(
            self.pointer,
            {
                "snapshot_id": snapshot_id,
                "previous_snapshot_id": previous or "legacy",
                "activated_at": utc_now(),
            },
        )

"""Content-addressed public observations with provenance and point-in-time reads."""

from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path
import re

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quant.data.snapshots import sha256_file, utc_now, write_json

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class DataCatalog:
    """Store source vintages independently of the TDX compatibility snapshot."""

    def __init__(self, data_root: Path):
        self.root = Path(data_root) / "lake"

    def dataset_dir(self, dataset: str) -> Path:
        """Validate dataset identifiers before accessing disk."""
        if not _NAME.fullmatch(dataset):
            raise ValueError("invalid dataset identifier")
        return self.root / dataset

    def ingest(
        self,
        dataset: str,
        raw: bytes,
        frame: pd.DataFrame,
        *,
        source: dict,
        parser_version: str,
        quality: dict,
        metadata: dict | None = None,
    ) -> dict:
        """Serialize publication for each dataset; readers only see completed vintages."""
        directory = self.dataset_dir(dataset)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".writer.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("another publisher is updating this dataset") from exc
            try:
                return self._ingest(
                    dataset,
                    raw,
                    frame,
                    source=source,
                    parser_version=parser_version,
                    quality=quality,
                    metadata=metadata,
                )
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _ingest(
        self,
        dataset: str,
        raw: bytes,
        frame: pd.DataFrame,
        *,
        source: dict,
        parser_version: str,
        quality: dict,
        metadata: dict | None = None,
    ) -> dict:
        """Save raw evidence and explicit Arrow types; never rewrite a vintage."""
        if source.get("persistent_storage") is False:
            raise PermissionError("source license prohibits persistent storage")
        if frame.empty:
            raise ValueError("empty source observations cannot be published")
        if "date" in frame and pd.to_datetime(frame["date"]).isna().any():
            raise ValueError("missing observation date cannot be published")
        directory = self.dataset_dir(dataset)
        raw_hash = hashlib.sha256(raw).hexdigest()
        fingerprint = hashlib.sha256(
            (
                "schema2"
                + raw_hash
                + parser_version
                + json.dumps(source, sort_keys=True)
                + json.dumps(metadata or {}, sort_keys=True)
                + json.dumps(quality, sort_keys=True)
            ).encode()
        ).hexdigest()[:24]
        pointer = directory / "latest.json"
        previous = json.loads(pointer.read_text())["version"] if pointer.exists() else None
        if (directory / fingerprint / "manifest.json").exists() and previous != fingerprint:
            # A provider reverting to old content is a new observation, not a rewind.
            fingerprint = hashlib.sha256((fingerprint + utc_now()).encode()).hexdigest()[:24]
        target = directory / fingerprint
        manifest_path = target / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            self.verify_manifest(manifest)
            write_json(directory / "latest.json", {"version": fingerprint})
            return manifest
        target.mkdir(parents=True, exist_ok=True)
        retrieved_at = utc_now()
        data = frame.copy()
        if "date" in data:
            data["date"] = pd.to_datetime(data["date"]).dt.date
        for name in ("symbol", "currency"):
            if name in data:
                data[name] = data[name].astype("string")
        for name in ("available_at", "announced_at", "retrieved_at"):
            if name in data:
                data[name] = pd.to_datetime(data[name], utc=True)
        data["retrieved_at"] = pd.Timestamp(retrieved_at)
        fields = []
        for name in data:
            if name == "date" or name in {"ex_date", "pay_date", "record_date"}:
                fields.append(pa.field(name, pa.date32()))
                data[name] = pd.to_datetime(data[name]).dt.date
            elif name.endswith("_at"):
                fields.append(pa.field(name, pa.timestamp("us", tz="UTC")))
            elif name in {"symbol", "currency", "contract", "metric", "methodology"}:
                fields.append(pa.field(name, pa.string()))
            elif name in {
                "open",
                "high",
                "low",
                "close",
                "amount",
                "settlement",
                "previous_settlement",
            } or name.startswith(("pe_", "dividend_yield")):
                data[name] = pd.to_numeric(data[name], errors="raise").astype("float64")
                fields.append(pa.field(name, pa.float64()))
            elif name in {"volume", "open_interest"}:
                fields.append(pa.field(name, pa.int64()))
            else:
                fields.append(pa.field(name, pa.Schema.from_pandas(data[[name]]).field(name).type))
        schema = pa.schema(
            fields,
            metadata={
                b"schema_version": b"2",
                b"dataset": dataset.encode(),
                b"parser_version": parser_version.encode(),
            },
        )
        (target / "raw.bin").write_bytes(raw)
        market = str((metadata or {}).get("market", "UNSPECIFIED"))
        if not _NAME.fullmatch(market):
            raise ValueError("invalid partition market")
        data_files = []
        groups = (
            data.groupby(pd.to_datetime(data["date"]).dt.year, dropna=False)
            if "date" in data
            else [("undated", data)]
        )
        for year, part in groups:
            payload = target / "data" / f"market={market}" / f"year={year}" / "part-000.parquet"
            payload.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                pa.Table.from_pandas(part, schema=schema, preserve_index=False),
                payload,
                compression="zstd",
            )
            data_files.append(
                {
                    "path": str(payload.relative_to(target)),
                    "sha256": sha256_file(payload),
                    "rows": len(part),
                }
            )
        data_hash = hashlib.sha256(json.dumps(data_files, sort_keys=True).encode()).hexdigest()
        manifest = {
            "dataset": dataset,
            "version": fingerprint,
            "schema_version": 2,
            "parser_version": parser_version,
            "source": source,
            "retrieved_at": retrieved_at,
            "previous_version": previous,
            "raw_sha256": raw_hash,
            "data_sha256": data_hash,
            "data_files": data_files,
            "market": market,
            "arrow_schema": str(schema),
            "rows": len(data),
            "quality": quality,
            "metadata": metadata or {},
            "first_date": str(data["date"].min()) if len(data) and "date" in data else None,
            "last_date": str(data["date"].max()) if len(data) and "date" in data else None,
        }
        write_json(manifest_path, manifest)
        write_json(directory / "latest.json", {"version": fingerprint})
        return manifest

    def manifest(self, dataset: str, version: str | None = None) -> dict:
        """Read a pinned version, defaulting to the current dataset pointer."""
        directory = self.dataset_dir(dataset)
        if version is None:
            version = json.loads((directory / "latest.json").read_text())["version"]
        if not _NAME.fullmatch(version):
            raise ValueError("invalid version")
        return json.loads((directory / version / "manifest.json").read_text())

    def verify_manifest(self, manifest: dict) -> None:
        """Check raw evidence and every standard partition, including old schema1 vintages."""
        directory = self.dataset_dir(manifest["dataset"]) / manifest["version"]
        if sha256_file(directory / "raw.bin") != manifest["raw_sha256"]:
            raise ValueError("raw dataset checksum failed")
        files = manifest.get(
            "data_files", [{"path": "data.parquet", "sha256": manifest["data_sha256"]}]
        )
        for item in files:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("invalid partition path")
            if sha256_file(directory / relative) != item["sha256"]:
                raise ValueError("dataset checksum failed")

    def read(
        self,
        dataset: str,
        *,
        version: str | None = None,
        as_of: str | pd.Timestamp | None = None,
        strict_pit: bool = False,
    ) -> pd.DataFrame:
        """Read a frozen vintage, filtering actual availability before revisions."""
        manifest = self.manifest(dataset, version)
        if strict_pit and not manifest["quality"].get("pit_verified", False):
            raise ValueError("historical publication/vintage evidence not verified")
        self.verify_manifest(manifest)
        directory = self.dataset_dir(dataset) / manifest["version"]
        files = manifest.get("data_files", [{"path": "data.parquet"}])
        frame = pd.concat(
            [pq.ParquetFile(directory / row["path"]).read().to_pandas() for row in files],
            ignore_index=True,
        )
        if "date" in frame:
            frame = frame.sort_values([c for c in ("symbol", "date") if c in frame]).reset_index(
                drop=True
            )
        if as_of is not None:
            if "available_at" not in frame:
                raise ValueError("as_of requires available_at")
            cutoff = pd.Timestamp(as_of)
            cutoff = (
                cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
            )
            frame = frame[pd.to_datetime(frame["available_at"], utc=True) <= cutoff].copy()
        return frame

    def observations(
        self, dataset: str, *, version: str | None = None, strict_pit: bool = False
    ) -> pd.DataFrame:
        """All saved observations up to a pinned vintage; retain revision availability."""
        pinned = self.manifest(dataset, version)
        cutoff = pd.Timestamp(pinned["retrieved_at"])
        parts = []
        for path in sorted(self.dataset_dir(dataset).glob("*/manifest.json")):
            manifest = json.loads(path.read_text())
            if pd.Timestamp(manifest["retrieved_at"]) > cutoff:
                continue
            frame = self.read(dataset, version=manifest["version"], strict_pit=strict_pit)
            frame["revision_version"] = manifest["version"]
            parts.append(frame)
        if not parts:
            raise ValueError("no complete observation vintages")
        return pd.concat(parts, ignore_index=True).sort_values(
            [c for c in ("available_at", "date", "retrieved_at") if c in parts[0]]
        )

    def history(
        self,
        dataset: str,
        *,
        as_of: str | pd.Timestamp,
        version: str | None = None,
        strict_pit: bool = True,
    ) -> pd.DataFrame:
        """Latest available revision per economic key at a given decision time."""
        frame = self.observations(dataset, version=version, strict_pit=strict_pit)
        cutoff = pd.Timestamp(as_of)
        if cutoff.tzinfo is None:
            raise ValueError("as_of must include timezone")
        if "available_at" not in frame:
            raise ValueError("historical query requires availability timestamps")
        frame = frame[pd.to_datetime(frame.available_at, utc=True) <= cutoff.tz_convert("UTC")]
        return (
            frame.sort_values(["available_at", "retrieved_at"])
            .drop_duplicates(["symbol", "date"], keep="last")
            .sort_values(["symbol", "date"])
        )

    def list_datasets(self) -> list[dict]:
        """List accepted/current vintages; incomplete downloads are not advertised."""
        if not self.root.exists():
            return []
        return [
            self.manifest(path.name)
            for path in sorted(self.root.iterdir())
            if path.is_dir() and (path / "latest.json").exists()
        ]

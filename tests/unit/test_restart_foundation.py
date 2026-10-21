from __future__ import annotations

import json
from pathlib import Path
import struct

import pandas as pd
import pytest

from quant.backtest.metrics import geometric_metrics, xirr
from quant.config import Settings
from quant.data.snapshots import SnapshotStore
from quant.etl.staging import parse_day_bytes
from quant.etl.update import apply_update


def test_etf_milliprice_and_extended_volume_are_decoded() -> None:
    # Observed TDX C364 marker retains quotient and a two-digit remainder.
    raw = struct.pack(
        "<IIIIIfII", 20261019, 1400, 1450, 1390, 1405, 7_560_448_000.0, 53_514_472, 0xC364002F
    )
    row = parse_day_bytes(raw, "sh588000").iloc[0]
    assert row["close"] == 1.405
    assert row["volume"] == 5_351_447_247
    assert row["low"] <= row["amount"] / row["volume"] <= row["high"]


def test_drawdown_includes_initial_capital_peak() -> None:
    metrics = geometric_metrics(pd.Series([-0.5, 1.0, -0.25]), periods_per_year=3)
    assert metrics["total_return"] == pytest.approx(-0.25)
    assert metrics["max_drawdown"] == pytest.approx(-0.5)
    assert metrics["annualized_return"] == pytest.approx(-0.25)
    with pytest.raises(ValueError):
        geometric_metrics(pd.Series([-1.1]))


def test_xirr_handles_contributions_and_zero_growth() -> None:
    assert xirr(
        [
            (pd.Timestamp("2020-01-01"), -100),
            (pd.Timestamp("2020-07-01"), -100),
            (pd.Timestamp("2021-01-01"), 200),
        ]
    ) == pytest.approx(0, abs=1e-12)
    assert xirr(
        [(pd.Timestamp("2020-01-01"), -100), (pd.Timestamp("2021-01-01"), 110)]
    ) == pytest.approx(1.1 ** (365.2425 / 366) - 1)


def test_snapshot_publish_verify_rollback_and_failed_publish(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    snapshot_id, directory = store.create()
    (directory / "staging").mkdir()
    (directory / "staging/payload.txt").write_text("original")
    store.seal(snapshot_id, {"publication_status": "validated"})
    store.activate(snapshot_id)
    assert Settings(data_root=tmp_path).staging_dir == directory / "staging"
    assert store.verify(snapshot_id)["ok"]
    (directory / "staging/payload.txt").write_text("corrupt")
    assert not store.verify(snapshot_id)["ok"]
    with pytest.raises(ValueError, match="integrity"):
        store.activate(snapshot_id)
    store.activate("legacy")
    assert Settings(data_root=tmp_path).staging_dir == tmp_path / "staging"
    failed, folder = store.create()
    store.seal(failed, {"publication_status": "failed"})
    with pytest.raises(ValueError, match="validation"):
        store.activate(failed)
    assert json.loads(store.pointer.read_text())["snapshot_id"] == "legacy"


def test_update_rejects_mutating_sealed_snapshot(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="sealed"):
        apply_update(tmp_path / "staging", tmp_path / "qlib", pd.DataFrame())


def test_index_lots_and_statistics_classification():
    import numpy as np
    from quant.etl.staging import DAY_DTYPE, _classify_security, parse_day_bytes

    raw = np.zeros(1, dtype=DAY_DTYPE)
    raw["date"] = 20261019
    for column in ("open", "high", "low", "close"):
        raw[column] = 417453
    raw["volume"] = 151084956
    raw["amount"] = 363447753986
    frame = parse_day_bytes(raw.tobytes(), "sh000300")
    assert frame.iloc[0].volume == 15108495600
    assert _classify_security("sh880006")[0] == "statistics"
    assert _classify_security("sz395013")[0] == "statistics"


def test_real_small_pipeline_failure_resume_and_historical_correction(tmp_path, monkeypatch):
    import zipfile
    import quant.etl.restart as restart

    source = tmp_path / "tdx"
    day = source / "vipdoc/sh/lday/sh600000.day"
    day.parent.mkdir(parents=True)
    (source / "T0002/hq_cache").mkdir(parents=True)
    (source / "T0002/hq_cache/gbbq").write_bytes(struct.pack("<I", 0))

    def record(date, price):
        return struct.pack("<IIIIIfII", date, price, price, price, price, 1000.0, 100, 0)

    archive = tmp_path / "baseline.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("sh/lday/sh600000.day", record(20200102, 1000) + record(20200106, 1000))
    day.write_bytes(record(20200103, 1200) + record(20200106, 1300))
    calls = []

    def metadata(raw, staging):
        calls.append("metadata")
        pd.DataFrame(columns=["category", "symbol", "date", "c1", "c2", "c3", "c4"]).to_parquet(
            staging / "gbbq.parquet"
        )
        return 0

    original_derive = restart._derive

    def failed_derive(staging):
        assert calls == ["metadata"]
        raise RuntimeError("injected interruption")

    monkeypatch.setattr(restart, "build_gbbq_staging", metadata)
    monkeypatch.setattr(restart, "build_blocks_staging", lambda *args: 0)
    monkeypatch.setattr(restart, "_derive", failed_derive)
    settings = Settings(
        _env_file=None, data_root=tmp_path / "data", tdx_home=source, tdx_zip=archive
    )
    with pytest.raises(RuntimeError, match="injected"):
        restart.update_snapshot(settings, workers=1)
    store = SnapshotStore(settings.data_root)
    assert store.current() is None
    identifier = next(store.root.iterdir()).name
    progress = json.loads((store.path(identifier) / "progress.json").read_text())
    assert progress["completed"] == ["source", "metadata", "daily", "securities"]
    day.write_bytes(
        record(20200106, 5000)
    )  # Changed external files cannot alter frozen resume input.
    monkeypatch.setattr(restart, "_derive", original_derive)
    resumed = restart.update_snapshot(settings, workers=1, resume=identifier)
    assert resumed["published"] and resumed["rows"] == 3
    frame = pd.read_parquet(settings.staging_dir / "daily").sort_values("date")
    assert frame.close.tolist() == [10.0, 12.0, 13.0]
    assert calls == ["metadata"] and store.verify(identifier)["ok"]

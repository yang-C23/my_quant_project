from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pandas as pd

from quant.etl.qlib_dump import dump_cn_daily
from quant.etl.update import apply_update, collect_new_rows, read_day_tail

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _hash_tree(root: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _copy_staging(tmp_path: Path) -> Path:
    staging = tmp_path / "staging"
    shutil.copytree(FIXTURES / "staging_mini", staging)
    return staging


def _next_row(staging: Path, symbol: str = "sh600000", date: str = "2021-08-10") -> pd.DataFrame:
    daily = pd.read_parquet(staging / "daily")
    row = daily[daily["symbol"].eq(symbol)].sort_values("date").tail(1).copy()
    row["date"] = pd.Timestamp(date)
    row["open"] = row["open"].astype(float) + 0.1
    row["high"] = row["high"].astype(float) + 0.1
    row["low"] = row["low"].astype(float) + 0.1
    row["close"] = row["close"].astype(float) + 0.1
    row["amount"] = row["amount"].astype(float) + 1000.0
    row["volume"] = row["volume"].astype(int) + 100
    return row


def test_read_day_tail_short_long_and_exact_boundary(tmp_path: Path) -> None:
    raw = (FIXTURES / "tdx" / "lday" / "sz000001.day").read_bytes()
    path = tmp_path / "sample.day"
    path.write_bytes(raw[:96])

    assert read_day_tail(path, 10) == raw[:96]
    assert read_day_tail(path, 3) == raw[:96]
    assert read_day_tail(path, 2) == raw[32:96]


def test_collect_new_rows_filters_tail_dates(tmp_path: Path) -> None:
    target = tmp_path / "vipdoc" / "sz" / "lday"
    target.mkdir(parents=True)
    shutil.copy(FIXTURES / "tdx" / "lday" / "sz000001.day", target / "sz000001.day")

    got = collect_new_rows(tmp_path / "vipdoc", pd.Timestamp("2021-08-05"), margin=2)

    assert not got.empty
    assert got["symbol"].unique().tolist() == ["sz000001"]
    assert pd.to_datetime(got["date"]).min() > pd.Timestamp("2021-08-05")


def test_apply_update_is_idempotent_and_preserves_hash_on_second_run(tmp_path: Path) -> None:
    staging = _copy_staging(tmp_path)
    qlib_dir = tmp_path / "qlib"
    dump_cn_daily(staging, qlib_dir)
    new_rows = _next_row(staging)

    first = apply_update(staging, qlib_dir, new_rows)
    hashes_after_first = {"staging": _hash_tree(staging), "qlib": _hash_tree(qlib_dir)}
    second = apply_update(staging, qlib_dir, new_rows)

    assert first.new_rows == 1
    assert first.symbols == 1
    assert first.qlib_rebuilt
    assert second.new_rows == 0
    assert not second.qlib_rebuilt
    assert hashes_after_first == {"staging": _hash_tree(staging), "qlib": _hash_tree(qlib_dir)}


def test_apply_update_rewrites_adjust_and_qlib_when_xdxr_in_window(tmp_path: Path) -> None:
    staging = _copy_staging(tmp_path)
    qlib_dir = tmp_path / "qlib"
    dump_cn_daily(staging, qlib_dir)
    factor_path = qlib_dir / "features" / "sh600000" / "factor.day.bin"
    factor_before = hashlib.sha256(factor_path.read_bytes()).hexdigest()
    adjust_before = pd.read_parquet(staging / "adjust.parquet")

    gbbq = pd.read_parquet(staging / "gbbq.parquet")
    event = pd.DataFrame(
        {
            "symbol": ["sh600000"],
            "date": [pd.Timestamp("2021-08-10")],
            "category": [1],
            "c1": [1.0],
            "c2": [0.0],
            "c3": [0.0],
            "c4": [0.0],
        }
    )
    pd.concat([gbbq, event], ignore_index=True).to_parquet(
        staging / "gbbq.parquet", index=False, compression="zstd"
    )

    stats = apply_update(staging, qlib_dir, _next_row(staging))
    adjust_after = pd.read_parquet(staging / "adjust.parquet")
    before_first_qfq = adjust_before[adjust_before["symbol"].eq("sh600000")]["qfq_factor"].iloc[0]
    after_first_qfq = adjust_after[adjust_after["symbol"].eq("sh600000")]["qfq_factor"].iloc[0]
    factor_after = hashlib.sha256(factor_path.read_bytes()).hexdigest()

    assert stats.new_rows == 1
    assert after_first_qfq < before_first_qfq
    assert factor_after != factor_before


def test_no_new_rows_does_not_touch_adjust(tmp_path: Path) -> None:
    staging = _copy_staging(tmp_path)
    before = hashlib.sha256((staging / "adjust.parquet").read_bytes()).hexdigest()

    stats = apply_update(staging, tmp_path / "qlib", pd.DataFrame())
    after = hashlib.sha256((staging / "adjust.parquet").read_bytes()).hexdigest()

    assert stats.new_rows == 0
    assert before == after


def test_existing_date_correction_replaces_bar_without_duplicate(tmp_path: Path) -> None:
    staging = _copy_staging(tmp_path)
    before = pd.read_parquet(staging / "daily")
    replacement = before.iloc[[0]].copy()
    replacement["close"] = replacement["close"] * 1.01
    result = apply_update(staging, tmp_path / "qlib", replacement)
    after = pd.read_parquet(staging / "daily")
    assert len(after) == len(before)
    assert not after.duplicated(["symbol", "date"]).any()
    key = replacement.iloc[0]
    actual = after[
        (after["symbol"] == key["symbol"])
        & (pd.to_datetime(after["date"]) == pd.Timestamp(key["date"]))
    ]
    assert actual.iloc[0]["close"] == key["close"]
    assert result.new_rows == 1  # changed/upserted rows, including corrections

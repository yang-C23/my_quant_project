from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.etl.mirror import extract_zip_baseline
from quant.etl.staging import DAY_DTYPE, build_daily_staging, parse_day_bytes
from quant.etl.tdx_parser import collect_day_files, generate_symbol

FIXTURES = Path(__file__).parent.parent / "fixtures" / "tdx"
SYMBOLS = ["sh600000", "sz000001", "sh999999"]


def _expected(symbol: str) -> pd.DataFrame:
    df = pd.read_csv(FIXTURES / "expected" / f"{symbol}.csv", parse_dates=["date"])
    return df


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_parse_day_bytes_matches_v1_golden(symbol: str) -> None:
    buf = (FIXTURES / "lday" / f"{symbol}.day").read_bytes()
    df = parse_day_bytes(buf, symbol)
    assert df.attrs["n_skipped"] == 0

    expected = _expected(symbol)
    assert len(df) == len(expected)
    got = df.assign(date=pd.to_datetime(df["date"])).reset_index(drop=True)
    pd.testing.assert_frame_equal(got, expected, check_exact=True)


def _make_record(date: int, price100: int = 1000, volume: int = 100, amount: float = 1e6) -> bytes:
    rec = np.zeros(1, dtype=DAY_DTYPE)
    rec["date"] = date
    rec["open"] = rec["high"] = rec["low"] = rec["close"] = price100
    rec["volume"] = volume
    rec["amount"] = amount
    return rec.tobytes()


def test_parse_day_bytes_skips_corrupted_records() -> None:
    buf = (
        _make_record(20240102)
        + _make_record(0)  # invalid date
        + _make_record(19891231)  # before 1990 cutoff
        + _make_record(20240103)
        + b"\x00" * 16  # trailing partial record
    )
    df = parse_day_bytes(buf, "sh600000")
    assert list(df["date"].astype(str)) == ["2024-01-02", "2024-01-03"]
    assert df.attrs["n_skipped"] == 3  # 2 bad dates + 1 partial tail
    assert df["open"].iloc[0] == 10.0
    assert df["volume"].dtype == np.int64


def test_parse_day_bytes_empty() -> None:
    df = parse_day_bytes(b"", "sh600000")
    assert df.empty
    assert df.attrs["n_skipped"] == 0


def _build_mirror(tmp_path: Path) -> Path:
    mirror = tmp_path / "mirror"
    for symbol in SYMBOLS:
        exchange = symbol[:2]
        dst = mirror / "vipdoc" / exchange / "lday"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / "lday" / f"{symbol}.day", dst / f"{symbol}.day")
    return mirror


def test_build_daily_staging_end_to_end(tmp_path: Path) -> None:
    mirror = _build_mirror(tmp_path)
    staging = tmp_path / "staging"

    stats = build_daily_staging(mirror, staging, workers=2)

    assert stats.files_total == 3
    assert stats.files_failed == 0
    assert stats.records_skipped == 0
    assert stats.by_exchange == {"sh": 500, "sz": 200}
    assert stats.rows == 700

    out = pd.read_parquet(staging / "daily")
    assert len(out) == 700
    assert set(out["exchange"].astype(str).unique()) == {"sh", "sz"}

    # naturally sorted by (symbol, date) within each exchange partition
    sh = out[out["exchange"].astype(str) == "sh"]
    assert list(sh["symbol"].unique()) == ["sh600000", "sh999999"]
    assert sh.groupby("symbol")["date"].apply(lambda s: s.is_monotonic_increasing).all()

    # values survive the parquet roundtrip
    golden = _expected("sz000001")
    sz = out[out["symbol"] == "sz000001"].reset_index(drop=True)
    assert (pd.to_datetime(sz["date"]) == golden["date"]).all()
    assert (sz["close"] == golden["close"]).all()
    assert (sz["amount"] == golden["amount"]).all()


def test_build_daily_staging_raises_on_empty_mirror(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_daily_staging(tmp_path, tmp_path / "staging", workers=1)


def test_extract_zip_baseline_normalizes_backslashes_and_caches(tmp_path: Path) -> None:
    zip_path = tmp_path / "hist.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sh\\lday\\sh600000.day", _make_record(20200106))
        zf.writestr("sz\\lday\\sz000001.day", _make_record(20200106))
        zf.writestr("readme.txt", "not a day file")
    mirror = tmp_path / "mirror"

    stats = extract_zip_baseline(zip_path, mirror)
    assert stats.files == 2
    assert (mirror / "zip_baseline" / "sh600000.day").exists()
    assert (mirror / "zip_baseline" / "sz000001.day").exists()
    assert not list((mirror / "zip_baseline").glob("*.txt"))

    # second call is a cache hit: extraction skipped, files untouched
    mtime = (mirror / "zip_baseline" / "sh600000.day").stat().st_mtime_ns
    stats2 = extract_zip_baseline(zip_path, mirror)
    assert stats2.files == 2
    assert (mirror / "zip_baseline" / "sh600000.day").stat().st_mtime_ns == mtime


def test_build_daily_staging_unions_sources_vipdoc_wins(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    baseline = mirror / "zip_baseline"
    baseline.mkdir(parents=True)
    baseline.joinpath("sh600000.day").write_bytes(
        _make_record(20240102, 1000) + _make_record(20240103, 1100)
    )
    vipdoc = mirror / "vipdoc" / "sh" / "lday"
    vipdoc.mkdir(parents=True)
    vipdoc.joinpath("sh600000.day").write_bytes(
        _make_record(20240103, 1150) + _make_record(20240104, 1200)
    )

    stats = build_daily_staging(mirror, tmp_path / "staging", workers=1)

    assert stats.files_total == 2
    assert stats.rows == 3
    assert stats.rows_deduped == 1
    out = pd.read_parquet(tmp_path / "staging" / "daily").sort_values("date")
    assert list(out["date"].astype(str)) == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert list(out["close"]) == [10.0, 11.5, 12.0]  # 2024-01-03 taken from vipdoc


def test_collect_day_files_filters_and_sorts(tmp_path: Path) -> None:
    lday = tmp_path / "vipdoc" / "sh" / "lday"
    lday.mkdir(parents=True)
    for name in ["sh600001.day", "sh600000.day", "readme.txt", "xx123456.day"]:
        (lday / name).write_bytes(b"")
    files = collect_day_files(tmp_path)
    assert [symbol for _, symbol in files] == ["sh600000", "sh600001"]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("600000", ("sh600000", True)),
        ("688001", ("sh688001", True)),
        ("000001", ("sz000001", True)),
        ("300750", ("sz300750", True)),
        ("430047", ("bj430047", True)),
        ("920001", ("bj920001", True)),
        ("999999", ("999999", False)),
    ],
)
def test_generate_symbol(code: str, expected: tuple[str, bool]) -> None:
    assert generate_symbol(code) == expected

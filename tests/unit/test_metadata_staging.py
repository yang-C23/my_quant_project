from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from quant.etl import staging as staging_mod
from quant.etl.staging import (
    build_blocks_staging,
    build_flags_staging,
    build_gbbq_staging,
    build_securities_staging,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "tdx"


def _write_staging_table(staging_dir: Path, name: str, df: pd.DataFrame) -> None:
    path = staging_dir / f"{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _write_daily(staging_dir: Path, df: pd.DataFrame) -> None:
    daily = staging_dir / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    df.to_parquet(daily / "part-000.parquet", index=False)


def test_build_securities_staging_classifies_prefixes(tmp_path: Path) -> None:
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    cases = {
        "sh600000": ("sh", "stock", "main"),
        "sh601000": ("sh", "stock", "main"),
        "sh603000": ("sh", "stock", "main"),
        "sh605000": ("sh", "stock", "main"),
        "sz000001": ("sz", "stock", "main"),
        "sz001001": ("sz", "stock", "main"),
        "sz003001": ("sz", "stock", "main"),
        "sz300001": ("sz", "stock", "gem"),
        "sz301001": ("sz", "stock", "gem"),
        "sh688001": ("sh", "stock", "star"),
        "sh689001": ("sh", "stock", "star"),
        "bj430001": ("bj", "stock", "bse"),
        "bj830001": ("bj", "stock", "bse"),
        "bj870001": ("bj", "stock", "bse"),
        "bj920001": ("bj", "stock", "bse"),
        "sh999999": ("sh", "index", "index"),
        "sz399001": ("sz", "index", "index"),
    }
    rows = []
    for symbol in cases:
        for dt in (dates[0], dates[-1]):
            rows.append({"symbol": symbol, "date": dt, "close": 10.0})
    rows.extend({"symbol": "sh600999", "date": dt, "close": 10.0} for dt in dates)
    rows.append({"symbol": "sz000002", "date": dates[0], "close": 10.0})
    _write_daily(tmp_path, pd.DataFrame(rows))

    assert build_securities_staging(tmp_path) == len(cases) + 2
    securities = pd.read_parquet(tmp_path / "securities.parquet").set_index("symbol")

    for symbol, (exchange, sec_type, board) in cases.items():
        row = securities.loc[symbol]
        assert row["code"] == symbol[2:]
        assert row["exchange"] == exchange
        assert row["sec_type"] == sec_type
        assert row["board"] == board
        assert pd.isna(row["delist_date"])

    assert pd.Timestamp(securities.loc["sz000002", "delist_date"]) == dates[0]


def test_build_gbbq_staging_from_decoded_fixture(monkeypatch, tmp_path: Path) -> None:
    decoded = pd.read_csv(FIXTURES / "gbbq_sample_decoded.csv", parse_dates=["date"])
    records = [
        (
            int(row.category),
            row.symbol,
            row.date.date(),
            float(row.c1),
            float(row.c2),
            float(row.c3),
            float(row.c4),
        )
        for row in decoded.itertuples(index=False)
    ]

    hq_cache = tmp_path / "tdx" / "T0002" / "hq_cache"
    hq_cache.mkdir(parents=True)
    (hq_cache / "gbbq").write_bytes(b"fixture")
    monkeypatch.setattr(staging_mod, "decode_gbbq_file", lambda _: records)

    assert build_gbbq_staging(tmp_path / "tdx", tmp_path / "staging") == 2
    got = pd.read_parquet(tmp_path / "staging" / "gbbq.parquet")

    assert list(got["symbol"]) == ["sh600000", "sz000001"]
    assert list(got["category"]) == [5, 1]
    assert got.loc[got["symbol"] == "sz000001", "c3"].iloc[0] == 2.0


def test_build_blocks_staging_parses_blocks_members_and_holidays(tmp_path: Path) -> None:
    hq_cache = tmp_path / "tdx" / "T0002" / "hq_cache"
    hq_cache.mkdir(parents=True)
    (hq_cache / "needini.dat").write_text("Y2024=2024,0101,0209\n", encoding="utf-8")
    (hq_cache / "tdxzs3.cfg").write_bytes(
        "ST板块|880001|4|||ST01\n行业一|880002|2|||ABCDE12\n".encode("gbk")
    )
    (hq_cache / "tdxhy.cfg").write_text(
        "1|600000|ST01|||HY02\n0|000001|HY01|||HY02\n", encoding="utf-8"
    )

    rows = build_blocks_staging(tmp_path / "tdx", tmp_path / "staging")

    blocks = pd.read_parquet(tmp_path / "staging" / "blocks.parquet")
    members = pd.read_parquet(tmp_path / "staging" / "block_members.parquet")
    holidays = pd.read_parquet(tmp_path / "staging" / "holidays.parquet")

    assert rows == len(blocks) + len(members) + len(holidays)
    assert set(blocks["block_code"]) == {"ST01", "ABCDE12"}
    assert ("sh600000", "ST01") in set(members.itertuples(index=False, name=None))
    assert list(pd.to_datetime(holidays["date"]).dt.strftime("%Y-%m-%d")) == [
        "2024-01-01",
        "2024-02-09",
    ]


def test_build_flags_staging_suspension_limits_and_st_snapshot(tmp_path: Path) -> None:
    daily = pd.DataFrame(
        [
            ("sh600000", "2024-01-02", 10.5),
            ("sh600000", "2024-01-04", 9.5),
            ("sz300001", "2024-01-02", 12.0),
            ("sz300001", "2024-01-03", 10.0),
            ("sz300001", "2024-01-04", 8.0),
            ("bj920001", "2024-01-02", 13.0),
            ("bj920001", "2024-01-03", 13.0),
            ("bj920001", "2024-01-04", 10.0),
        ],
        columns=["symbol", "date", "close"],
    )
    daily["date"] = pd.to_datetime(daily["date"])
    basics = daily[["symbol", "date"]].copy()
    basics["preclose"] = 10.0
    securities = pd.DataFrame(
        [
            ("sh600000", "main", "2024-01-02", pd.NaT),
            ("sz300001", "gem", "2024-01-02", pd.NaT),
            ("bj920001", "bse", "2024-01-02", pd.NaT),
        ],
        columns=["symbol", "board", "list_date", "delist_date"],
    )
    blocks = pd.DataFrame([("ST01", "ST板块")], columns=["block_code", "block_name"])
    members = pd.DataFrame([("sh600000", "ST01")], columns=["stock_symbol", "block_code"])

    _write_daily(tmp_path, daily)
    _write_staging_table(tmp_path, "basics", basics)
    _write_staging_table(tmp_path, "securities", securities)
    _write_staging_table(tmp_path, "blocks", blocks)
    _write_staging_table(tmp_path, "block_members", members)

    assert build_flags_staging(tmp_path) == 9
    flags = pd.read_parquet(tmp_path / "flags.parquet")
    flags["date"] = pd.to_datetime(flags["date"])

    sh = flags[flags["symbol"] == "sh600000"].set_index("date")
    assert bool(sh.loc[pd.Timestamp("2024-01-02"), "is_st"])
    assert bool(sh.loc[pd.Timestamp("2024-01-02"), "is_limit_up"])
    assert bool(sh.loc[pd.Timestamp("2024-01-03"), "is_suspended"])
    assert np.isnan(sh.loc[pd.Timestamp("2024-01-03"), "limit_up_price"])
    assert bool(sh.loc[pd.Timestamp("2024-01-04"), "is_limit_down"])

    gem = flags[flags["symbol"] == "sz300001"].set_index("date")
    assert gem.loc[pd.Timestamp("2024-01-02"), "limit_up_price"] == 12.0
    assert bool(gem.loc[pd.Timestamp("2024-01-02"), "is_limit_up"])

    bse = flags[flags["symbol"] == "bj920001"].set_index("date")
    assert np.isnan(bse.loc[pd.Timestamp("2024-01-02"), "limit_up_price"])
    assert not bool(bse.loc[pd.Timestamp("2024-01-02"), "is_limit_up"])
    assert bse.loc[pd.Timestamp("2024-01-03"), "limit_up_price"] == 13.0
    assert bool(bse.loc[pd.Timestamp("2024-01-03"), "is_limit_up"])

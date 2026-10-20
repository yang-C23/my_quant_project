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


def _tnf_record(code: str, name: str) -> bytes:
    record = bytearray(staging_mod._TNF_RECORD_SIZE)
    record[: len(code)] = code.encode("ascii")
    name_bytes = name.encode("gbk")
    start = staging_mod._TNF_NAME_OFFSET
    record[start : start + len(name_bytes)] = name_bytes
    return bytes(record)


def test_read_tnf_names_decodes_fixed_width_records(tmp_path: Path) -> None:
    tnf = tmp_path / "shs.tnf"
    tnf.write_bytes(
        (b"\0" * staging_mod._TNF_HEADER_SIZE)
        + _tnf_record("600000", "浦发银行")
        + _tnf_record("688001", "华兴源创")
    )

    assert staging_mod._read_tnf_names(tnf, "sh") == {
        "sh600000": "浦发银行",
        "sh688001": "华兴源创",
    }


def test_build_securities_staging_classifies_prefixes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        staging_mod,
        "_tdx_security_names",
        lambda: {"sh600000": "浦发银行", "sz000001": "平安银行"},
    )
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    cases = {
        "sh600000": ("sh", "stock", "main"),
        "sh601000": ("sh", "stock", "main"),
        "sh603000": ("sh", "stock", "main"),
        "sh605000": ("sh", "stock", "main"),
        "sz000001": ("sz", "stock", "main"),
        "sz001001": ("sz", "stock", "main"),
        "sz002001": ("sz", "stock", "main"),
        "sz003001": ("sz", "stock", "main"),
        "sz300001": ("sz", "stock", "gem"),
        "sz301001": ("sz", "stock", "gem"),
        "sz302132": ("sz", "stock", "main"),
        "sh688001": ("sh", "stock", "star"),
        "sh689001": ("sh", "stock", "star"),
        "bj430001": ("bj", "stock", "bse"),
        "bj830001": ("bj", "stock", "bse"),
        "bj870001": ("bj", "stock", "bse"),
        "bj920001": ("bj", "stock", "bse"),
        "sh999999": ("sh", "index", "index"),
        "sz399001": ("sz", "index", "index"),
        "sz395001": ("sz", "statistics", "statistics"),
        "sh880001": ("sh", "statistics", "statistics"),
        "sh881001": ("sh", "index", "index"),
        "sh887001": ("sh", "index", "index"),
        "sh888001": ("sh", "index", "index"),
        "sh110001": ("sh", "bond", "bond"),
        "sh111001": ("sh", "bond", "bond"),
        "sh113001": ("sh", "bond", "bond"),
        "sh118001": ("sh", "bond", "bond"),
        "sh132001": ("sh", "bond", "bond"),
        "sz123001": ("sz", "bond", "bond"),
        "sz125001": ("sz", "bond", "bond"),
        "sz126001": ("sz", "bond", "bond"),
        "sz127001": ("sz", "bond", "bond"),
        "sz128001": ("sz", "bond", "bond"),
        "sh204001": ("sh", "repo", "other"),
        "sz131001": ("sz", "repo", "other"),
        "sh900901": ("sh", "stock", "b"),
        "sz200001": ("sz", "stock", "b"),
        "sz201872": ("sz", "stock", "b"),
        "sh500001": ("sh", "fund", "other"),
        "sh520001": ("sh", "fund", "other"),
        "sh530001": ("sh", "fund", "other"),
        "sh551001": ("sh", "fund", "other"),
        "sh510001": ("sh", "etf", "etf"),
        "sh560001": ("sh", "etf", "etf"),
        "sh580001": ("sh", "etf", "etf"),
        "sz159001": ("sz", "etf", "etf"),
        "sz160001": ("sz", "etf", "etf"),
        "sz184001": ("sz", "fund", "other"),
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

    assert securities.loc["sh600000", "name"] == "浦发银行"
    assert securities.loc["sh601000", "name"] == "sh601000"
    assert securities.loc["sz000001", "name"] == "平安银行"
    assert pd.isna(securities.loc["sz395001", "name"])
    assert pd.Timestamp(securities.loc["sz000002", "delist_date"]) == dates[0]
    other = securities[securities["board"].eq("other")]
    assert len(other) <= 500
    assert not other.index.str.startswith("sz002").any()
    assert securities.loc["sz395001", "sec_type"] == "statistics"


def test_classify_security_unknown_prefix_is_not_stock() -> None:
    assert staging_mod._classify_security("sh777777") == ("other", "other")
    assert staging_mod._classify_security("sz200011") == ("stock", "b")


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
            ("sh999999", "2024-01-02", 10.0),
            ("sh110001", "2024-01-02", 10.0),
            ("sh510001", "2024-01-02", 10.0),
            ("sh900901", "2024-01-02", 10.0),
        ],
        columns=["symbol", "date", "close"],
    )
    daily["date"] = pd.to_datetime(daily["date"])
    basics = daily[["symbol", "date"]].copy()
    basics["preclose"] = 10.0
    securities = pd.DataFrame(
        [
            ("sh600000", "stock", "main", "2024-01-02", pd.NaT),
            ("sz300001", "stock", "gem", "2024-01-02", pd.NaT),
            ("bj920001", "stock", "bse", "2024-01-02", pd.NaT),
            ("sh999999", "index", "index", "2024-01-02", pd.NaT),
            ("sh110001", "bond", "bond", "2024-01-02", pd.NaT),
            ("sh510001", "etf", "etf", "2024-01-02", pd.NaT),
            ("sh900901", "stock", "b", "2024-01-02", pd.NaT),
        ],
        columns=["symbol", "sec_type", "board", "list_date", "delist_date"],
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
    assert set(flags["symbol"]) == {"sh600000", "sz300001", "bj920001"}

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

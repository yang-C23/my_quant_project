from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from quant.etl.qlib_dump import build_calendar, build_instruments, dump_cn_daily

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_build_calendar_and_instruments(tmp_path: Path) -> None:
    staging = FIXTURES / "staging_mini"

    calendar = build_calendar(staging)
    assert [dt.date().isoformat() for dt in calendar] == [
        "2021-08-02",
        "2021-08-03",
        "2021-08-04",
        "2021-08-05",
        "2021-08-06",
        "2021-08-09",
    ]

    build_instruments(staging, tmp_path)
    assert (tmp_path / "instruments" / "all.txt").read_text(encoding="utf-8").splitlines() == [
        "SH600000\t2021-08-02\t2021-08-09",
        "SH688001\t2021-08-02\t2021-08-05",
    ]
    assert (tmp_path / "instruments" / "nostar.txt").read_text(encoding="utf-8").splitlines() == [
        "SH600000\t2021-08-02\t2021-08-09"
    ]
    assert (tmp_path / "instruments" / "main_only.txt").read_text(
        encoding="utf-8"
    ).splitlines() == ["SH600000\t2021-08-02\t2021-08-09"]


def test_dump_cn_daily_readable_by_qlib(tmp_path: Path) -> None:
    import qlib
    from qlib.data import D

    staging = FIXTURES / "staging_mini"
    stats = dump_cn_daily(staging, tmp_path)

    assert stats.instruments == 2
    assert stats.rows == 10
    assert (tmp_path / "calendars" / "day.txt").exists()
    assert (tmp_path / "features" / "sh600000" / "close.day.bin").exists()

    qlib.init(provider_uri=str(tmp_path), region="cn", expression_cache=None, dataset_cache=None)
    got = D.features(
        ["SH600000"],
        ["$close", "$factor", "$volume"],
        start_time="2021-08-02",
        end_time="2021-08-09",
        disk_cache=0,
    )

    daily = pd.read_parquet(staging / "daily")
    adjust = pd.read_parquet(staging / "adjust.parquet")
    daily["date"] = pd.to_datetime(daily["date"])
    adjust["date"] = pd.to_datetime(adjust["date"])
    expected = (
        daily[daily["symbol"].eq("sh600000")]
        .merge(adjust, on=["symbol", "date"])
        .sort_values("date")
    )
    np.testing.assert_allclose(
        got["$close"].to_numpy(),
        (expected["close"] * expected["hfq_factor"]).astype("float32").to_numpy(),
        rtol=1e-6,
    )
    np.testing.assert_allclose(
        got["$factor"].to_numpy(),
        expected["hfq_factor"].astype("float32").to_numpy(),
        rtol=1e-6,
    )
    np.testing.assert_allclose(
        got["$volume"].to_numpy(),
        (expected["volume"] / expected["hfq_factor"]).astype("float32").to_numpy(),
        rtol=1e-6,
    )

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.etl.staging import parse_day_bytes
from quant.tdx import functions as F

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ── naive per-bar reference implementations (semantics oracle) ────────────────


def naive_recursive(x: list[float], alpha: float) -> list[float]:
    prev = math.nan
    out = []
    for v in x:
        if math.isnan(v):
            out.append(prev)
        else:
            prev = v if math.isnan(prev) else alpha * v + (1 - alpha) * prev
            out.append(prev)
    return out


def naive_rolling(x: list[float], n: int, fn) -> list[float]:
    out = []
    for i in range(len(x)):
        window = x[max(0, i - n + 1) : i + 1]
        out.append(fn(window) if i >= n - 1 and not any(map(math.isnan, window)) else math.nan)
    return out


def naive_barslast(cond: list[bool]) -> list[float]:
    last = None
    out = []
    for i, c in enumerate(cond):
        if c:
            last = i
        out.append(math.nan if last is None else float(i - last))
    return out


@pytest.fixture()
def rng_series() -> pd.Series:
    rng = np.random.default_rng(42)
    values = rng.normal(100, 10, size=300)
    values[:7] = np.nan  # leading NaN (warmup-style)
    values[[50, 51, 120]] = np.nan  # interior NaN (suspension-style)
    return pd.Series(values)


def test_sma_matches_naive_recursion(rng_series: pd.Series) -> None:
    for n, m in [(3, 1), (40, 4), (100, 50)]:
        got = F.SMA(rng_series, n, m)
        want = naive_recursive(list(rng_series), m / n)
        np.testing.assert_allclose(got, want, rtol=1e-12, equal_nan=True)


def test_ema_matches_naive_recursion(rng_series: pd.Series) -> None:
    for n in [10, 12, 26]:
        got = F.EMA(rng_series, n)
        want = naive_recursive(list(rng_series), 2.0 / (n + 1))
        np.testing.assert_allclose(got, want, rtol=1e-12, equal_nan=True)


def test_sma_rejects_bad_m(rng_series: pd.Series) -> None:
    with pytest.raises(ValueError):
        F.SMA(rng_series, 3, 0)
    with pytest.raises(ValueError):
        F.SMA(rng_series, 3, 4)


def test_rolling_primitives_match_naive(rng_series: pd.Series) -> None:
    x = list(rng_series)
    np.testing.assert_allclose(
        F.MA(rng_series, 5), naive_rolling(x, 5, lambda w: sum(w) / len(w)), equal_nan=True
    )
    np.testing.assert_allclose(F.HHV(rng_series, 9), naive_rolling(x, 9, max), equal_nan=True)
    np.testing.assert_allclose(F.LLV(rng_series, 9), naive_rolling(x, 9, min), equal_nan=True)
    np.testing.assert_allclose(F.SUM(rng_series, 14), naive_rolling(x, 14, sum), equal_nan=True)


def test_ref_shift(rng_series: pd.Series) -> None:
    assert F.REF(rng_series, 1).iloc[10] == rng_series.iloc[9]
    assert np.isnan(F.REF(rng_series, 3).iloc[2])


def test_count_every_exist() -> None:
    cond = pd.Series([True, False, True, True, np.nan, True]).astype(object)
    counts = F.COUNT(cond, 3)
    assert list(counts.iloc[2:]) == [2.0, 2.0, 2.0, 2.0]
    assert list(F.EVERY(cond, 2).iloc[2:]) == [False, True, False, False]
    assert list(F.EXIST(cond, 2).iloc[1:]) == [True, True, True, True, True]


def test_cross_semantics() -> None:
    a = pd.Series([1.0, 2.0, 3.0, 2.0, 3.0, np.nan, 4.0])
    b = pd.Series([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0])
    got = list(F.CROSS(a, b))
    # bar2: 3>2 with prev 2<=2 → True; bar4: 3>2 with prev 2<=2 → True
    assert got == [False, False, True, False, True, False, False]


def test_barslast_matches_naive() -> None:
    cond = pd.Series([False, True, False, False, True, False])
    np.testing.assert_allclose(F.BARSLAST(cond), naive_barslast(list(cond)), equal_nan=True)


def test_iif_nan_condition_selects_else_branch() -> None:
    cond = pd.Series([True, False, np.nan]).astype(object)
    got = F.IIF(cond, 1.0, pd.Series([9.0, 9.0, np.nan]))
    assert got.iloc[0] == 1.0
    assert got.iloc[1] == 9.0
    assert np.isnan(got.iloc[2])  # NaN cond → else branch (matches bt.If)


def test_hhv_llv_zero_window_expanding(rng_series: pd.Series) -> None:
    clean = rng_series.dropna().reset_index(drop=True)
    np.testing.assert_allclose(F.HHV(clean, 0), clean.cummax())
    np.testing.assert_allclose(F.LLV(clean, 0), clean.cummin())


# ── golden parity vs v1 backtrader reference ─────────────────────────────────


def _fixture_ohlcv(symbol: str) -> pd.DataFrame:
    buf = (FIXTURES / "tdx" / "lday" / f"{symbol}.day").read_bytes()
    return parse_day_bytes(buf, symbol).reset_index(drop=True)


def _golden(symbol: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "goldens" / f"bt_legacy_{symbol}.csv")


@pytest.mark.parametrize("symbol", ["sh600000", "sz000001"])
def test_tdx_sma_matches_bt_golden_exactly(symbol: str) -> None:
    df = _fixture_ohlcv(symbol)
    golden = _golden(symbol)
    # close has no NaN → bt TDXSMA seeds bar1 = x0, identical to our semantics
    np.testing.assert_allclose(
        F.SMA(df["close"], 3, 1), golden["sma_3_1"], rtol=1e-10, equal_nan=True
    )
    np.testing.assert_allclose(
        F.SMA(df["close"], 40, 4), golden["sma_40_4"], rtol=1e-10, equal_nan=True
    )


@pytest.mark.parametrize("symbol", ["sh600000", "sz000001"])
def test_kdj_composition_matches_bt_golden(symbol: str) -> None:
    """KDJ built purely from tdx.functions reproduces the bt_legacy golden.

    bt's TDXSMA clock follows the rsv line, so its recursion also seeds from
    the first valid RSV — k/d/j match exactly from bar n-1 onward, NaN before.
    """
    df = _fixture_ohlcv(symbol)
    golden = _golden(symbol)

    low9 = F.LLV(df["low"], 9)
    denom = F.HHV(df["high"], 9) - low9
    rsv = F.IIF(denom == 0, 0.0, (df["close"] - low9) / denom * 100.0)
    k = F.SMA(rsv, 3, 1)
    d = F.SMA(k, 3, 1)
    j = 3.0 * k - 2.0 * d

    np.testing.assert_allclose(k, golden["k"], rtol=1e-8, equal_nan=True)
    np.testing.assert_allclose(d, golden["d"], rtol=1e-8, equal_nan=True)
    np.testing.assert_allclose(j, golden["j"], rtol=1e-8, atol=1e-8, equal_nan=True)

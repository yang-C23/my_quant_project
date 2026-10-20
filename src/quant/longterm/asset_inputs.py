"""Corporate-action-aware marks and causal signals, retaining original quotes."""

from __future__ import annotations

import numpy as np
import pandas as pd


def prepare_action_prices(
    bars: pd.DataFrame, actions: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Correct stale halted marks and remove mechanical distributions from signals.

    Execution still uses unadjusted quotes and actual share/cash events. A stale
    pre-split quote on a halted ex-date is a valuation mark, never a fill. Signal
    total return recognizes a dividend receivable on ex-date; it is not a claim
    that cash was available for reinvestment that day.
    """
    if not bars.index.is_unique or not bars.index.is_monotonic_increasing:
        raise ValueError("ordered unique bars required")
    if actions.event_id.duplicated().any():
        raise ValueError("duplicate action identifiers")
    by_date = {}
    for action in actions.to_dict("records"):
        date = pd.Timestamp(action["ex_date"])
        if date not in bars.index:
            raise ValueError("company action without a calendar valuation session")
        if action["kind"] not in {"split", "dividend"}:
            raise ValueError("unsupported company action")
        by_date.setdefault(date, []).append(action)
    for group in by_date.values():
        if len({action["kind"] for action in group}) > 1:
            raise ValueError("same-day split and dividend require explicit per-share basis")
    execution = bars.copy()
    execution["close"] = execution.close.astype(float)
    execution["tradable"] = (
        bars["tradable"].astype("boolean").fillna(False)
        if "tradable" in bars
        else pd.Series(True, index=bars.index, dtype="boolean")
    )
    if "volume" in bars:
        execution["tradable"] &= bars.volume.notna() & bars.volume.gt(0)
    execution["observed_close"] = bars.close
    execution["mark_adjustment"] = 1.0
    signal = bars.copy()
    for column in ("open", "high", "low", "close"):
        if column in signal:
            signal[column] = signal[column].astype(float)
    adjustments = []
    previous_mark, previous_raw, accumulated = None, None, 1.0
    columns = [column for column in ("open", "high", "low", "close") if column in signal]
    signal_arrays = {column: signal[column].to_numpy(copy=True) for column in columns}
    raw_arrays = {column: bars[column].to_numpy() for column in columns}
    tradable = execution["tradable"].to_numpy()
    for i, date in enumerate(bars.index):
        group = by_date.get(date, [])
        ratio = float(np.prod([float(a["ratio"]) for a in group if a["kind"] == "split"]))
        dividend = sum(float(a["per_share"]) for a in group if a["kind"] == "dividend")
        if ratio <= 0 or dividend < 0:
            raise ValueError("invalid company action terms")
        quoted = float(raw_arrays["close"][i])
        mark = quoted
        halted = not bool(tradable[i])
        if previous_mark is not None and halted:
            theoretical = previous_mark / ratio - dividend
            if theoretical <= 0:
                raise ValueError("nonpositive post-action mark")
            if np.isclose(quoted, previous_raw, rtol=0, atol=1e-10):
                mark = theoretical
                if mark != quoted:
                    adjustments.append(
                        {
                            "date": date,
                            "observed_close": quoted,
                            "valuation_mark": mark,
                            "reason": "halted_stale_quote_after_verified_company_action",
                            "tradable": False,
                        }
                    )
                    execution.loc[date, "close"] = mark
                    execution.loc[date, "mark_adjustment"] = mark / quoted
                    execution.loc[date, "tradable"] = False
            elif group and not np.isclose(quoted, theoretical, rtol=0, atol=0.00051):
                raise ValueError("halted company-action quote requires manual adjudication")
        if previous_mark is not None:
            gross_factor = (ratio * (mark + dividend)) / previous_mark
            # accumulated is the signal index / preceding unadjusted valuation mark.
            accumulated = accumulated * previous_mark * gross_factor / mark
        for column in columns:
            value = mark if column == "close" else raw_arrays[column][i]
            signal_arrays[column][i] = float(value) * accumulated
        if halted:
            # No invented intraday high/low for KDJ on a nontrading session.
            for column in ("open", "high", "low"):
                if column in signal_arrays:
                    signal_arrays[column][i] = np.nan
        previous_mark, previous_raw = mark, quoted
    for column, values in signal_arrays.items():
        signal[column] = values
    execution["tradable"] = execution["tradable"].astype(bool)
    return execution, signal, pd.DataFrame(adjustments)

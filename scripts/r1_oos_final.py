"""R1 OOS final adjudication — reviewer-only (TASK-066).

Runs each surviving IS candidate plus its z-ge original baseline exactly once
on the protected OOS window 2022-01-01..2024-12-31, per docs/research/PLAN.md.
The `myquant research` CLI hard-rejects post-IS dates by design; this script is
the single sanctioned bypass and must never be invoked by the development agent.

Usage:
    python scripts/r1_oos_final.py --i-am-the-reviewer
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

OOS_START = "2022-01-01"
OOS_END = "2024-12-31"
# 载入自 2021-06 起：为指标 warmup 提供 ~140 交易日，信号/持仓自 OOS 首日起算
LOAD_START = "2021-06-01"
SAMPLE_SEED = 42
SAMPLE_SIZE = 800  # 与 IS 扫描同一抽样（时间泛化检验；全宇宙确认留给 Tier3）
REPORT = Path("docs/reviews/R1-final-report.md")


def _amv_section() -> list[str]:
    from quant.data.api import get_ohlcv
    from quant.indicators.amv import amv
    from quant.research.amv_timing import build_variant_signal, evaluate_timing

    index_df = get_ohlcv(
        "sh999999",
        start=LOAD_START,
        end=OOS_END,
        adjust="qfq",
        fields=("open", "high", "low", "close", "volume", "amount"),
    )
    amv_df = amv(index_df, k=2.13)
    rows = []
    for tag, variant in (("baseline_immediate", "immediate"), ("candidate_confirm_life", "confirm_life")):
        signal = build_variant_signal(
            amv_df, index_df["close"], buy_th=4.0, sell_th=-2.3, variant=variant
        )
        # 从 OOS 前最后一个交易日起切片：shift(1) 的持仓携带跨年状态，该日收益贡献为 0
        cut = index_df.index[index_df.index < pd.Timestamp(OOS_START)][-1]
        sliced_signal = signal.loc[signal.index >= cut]
        sliced_close = index_df["close"].loc[index_df.index >= cut]
        stats = evaluate_timing(amv_df.loc[amv_df.index >= cut], sliced_signal, sliced_close)
        rows.append(
            {
                "run": tag,
                "cumulative": stats.cumulative_return,
                "annual": stats.annual_return,
                "max_dd": stats.max_drawdown,
                "waves": stats.wave_count,
                "win": stats.win_rate,
                "profit_factor": stats.profit_factor,
                "median_wave": stats.median_wave_return,
                "switches_per_year": stats.switches_per_year,
            }
        )
    frame = pd.DataFrame(rows)
    return ["## AMV（TASK-061 候选）", "", frame.round(4).to_markdown(index=False), ""]


def _pair_prices_and_signals(kind: str) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    from quant.data.universe import list_symbols
    from quant.indicators.dual_trend import dual_trend
    from quant.research.optimize import sample_symbols
    from quant.research.trade_pairs import _load_prices, _shortterm_inputs, _signal_frame

    symbols = sample_symbols(
        list_symbols(exclude_boards={"star", "b"}, at=None), SAMPLE_SIZE, SAMPLE_SEED
    )
    signal_start = pd.Timestamp(OOS_START)
    if kind == "shortterm":
        prices, entries = _shortterm_inputs(symbols, LOAD_START, OOS_END, signal_start)
        return prices, entries, {}
    frames, entry_parts, exit_parts = [], {"golden_cross": [], "dual_entry": []}, {"dead_cross": []}
    for symbol in symbols:
        try:
            frame = _load_prices(symbol, LOAD_START, OOS_END)
        except ValueError:
            continue
        dt = dual_trend(frame.set_index("date"))
        frames.append(frame[frame["date"].ge(signal_start)].copy())
        dt = dt.loc[dt.index >= signal_start]
        entry_parts["golden_cross"].append(_signal_frame(symbol, dt.index, dt["sig_golden_cross"]))
        entry_parts["dual_entry"].append(_signal_frame(symbol, dt.index, dt["sig_dual_trend_entry"]))
        exit_parts["dead_cross"].append(_signal_frame(symbol, dt.index, dt["sig_dead_cross"]))
    prices = pd.concat(frames, ignore_index=True)
    entries = {k: pd.concat(v, ignore_index=True) for k, v in entry_parts.items()}
    exits = {k: pd.concat(v, ignore_index=True) for k, v in exit_parts.items()}
    return prices, entries, exits


def _dual_trend_section(candidates: list[dict]) -> list[str]:
    from quant.research.trade_pairs import run_pair_study

    prices, entries, exits = _pair_prices_and_signals("dual_trend")
    rows = []
    for cand in candidates:
        result = run_pair_study(
            entries[cand["entry"]],
            {"dead_cross": exits["dead_cross"]} if cand["exit"] == "dead_cross" else {},
            prices,
            max_hold=int(cand.get("max_hold", 120)),
            stop_loss=cand.get("stop_loss"),
        )
        summary = result.summary.iloc[0].to_dict()
        rows.append({"entry": cand["entry"], "exit": cand["exit"], **summary})
    frame = pd.DataFrame(rows)
    return ["## 双线（TASK-063 候选）", "", frame.round(4).to_markdown(index=False), ""]


def _shortterm_section(candidates: list[dict]) -> list[str]:
    from quant.research.trade_pairs import _coerce_stop_value, run_pair_study

    prices, entries, _ = _pair_prices_and_signals("shortterm")
    rows = []
    for cand in candidates:
        result = run_pair_study(
            entries[cand["entry"]],
            {},
            prices,
            max_hold=int(cand["max_hold"]),
            stop_loss=_coerce_stop_value(str(cand["stop"])),
            two_day_no_profit=bool(cand.get("two_day_no_profit", True)),
        )
        summary = result.summary.iloc[0].to_dict()
        rows.append({"entry": cand["entry"], "max_hold": cand["max_hold"], "stop": cand["stop"], **summary})
    frame = pd.DataFrame(rows)
    return ["## 单针/砖形（TASK-064 候选）", "", frame.round(4).to_markdown(index=False), ""]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--i-am-the-reviewer", action="store_true")
    args = parser.parse_args()
    if not args.i_am_the_reviewer:
        print("protected OOS path: reviewer confirmation flag required", file=sys.stderr)
        return 2

    # 候选注册表：与各 findings 的 Candidate params JSON 一一对应，OOS 各跑一次
    dual_candidates: list[dict] = []  # 由审查者按 findings/TASK-063.md 填写
    short_candidates: list[dict] = []  # 由审查者按 findings/TASK-064.md 填写

    lines = [
        "# R1 Final Report — OOS 裁定（TASK-066）",
        "",
        f"- OOS window: {OOS_START} .. {OOS_END}（每候选+基线各一次，审查者执行）",
        f"- 股票类样本：与 IS 相同的 seed={SAMPLE_SEED} 均匀抽样 {SAMPLE_SIZE} 只（时间泛化检验）",
        "- Tier1 无费用口径；采纳仅指进入 Tier3（Backtrader+costs）验证队列",
        "",
    ]
    lines += _amv_section()
    if dual_candidates:
        lines += _dual_trend_section(dual_candidates)
    if short_candidates:
        lines += _shortterm_section(short_candidates)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"OOS report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

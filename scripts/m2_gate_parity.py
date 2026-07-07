#!/usr/bin/env python
"""M2 gate: reproduce the v1 kdj_j0 full-market study on v1's exact universe.

One-command reproduction:
    python scripts/m2_gate_parity.py

Universe = the symbol list embedded in the v1 golden report itself
(docs/parity/pipeline_kdj_forward_return_*.csv), which includes assets v1's
PG securities misclassified as stocks (convertible bonds sh110xxx, etc.).
v2's production universe intentionally excludes those (TASK-011); the gate
isolates ENGINE equivalence by replaying identical inputs.

Tolerances (docs/backtest_platform.md §5): per-horizon sample counts equal,
win-rate diff <= 0.1pp, avg-return diff <= 5bps.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

GOLDEN = Path("docs/parity/pipeline_kdj_forward_return_20260311_225334_summary.csv")
OUT = Path("docs/reviews/M2-gate-report.md")
START, END = "2015-01-01", "2024-12-31"


def main() -> int:
    from quant.research.forward_returns import run_event_study
    from quant.signals.factors import compute_signal

    golden = pd.read_csv(GOLDEN)
    universe = sorted(set(golden.loc[golden["symbol"] != "ALL", "symbol"]))
    print(f"v1 universe from golden report: {len(universe)} symbols")

    t0 = time.monotonic()
    signals = compute_signal(
        "kdj_oversold",
        universe,
        start=START,
        end=END,
        signal_params={"j_threshold": 0, "sma_mode": "simple"},
    )
    result = run_event_study(
        signals, horizons=[1, 3, 5], start=START, end=END, entry_filters="none"
    )
    elapsed = time.monotonic() - t0

    ga = golden[golden["symbol"] == "ALL"].set_index("horizon")
    va = result.pooled.set_index("horizon")
    rows = []
    ok = True
    for h in (1, 3, 5):
        cnt_eq = int(ga.loc[h, "count"]) == int(va.loc[h, "count"])
        sig_eq = int(ga.loc[h, "signals"]) == int(va.loc[h, "signals"])
        win_d = abs(float(ga.loc[h, "win_rate"]) - float(va.loc[h, "win_rate"])) * 100
        avg_d = abs(float(ga.loc[h, "avg_return"]) - float(va.loc[h, "avg_return"])) * 1e4
        passed = cnt_eq and win_d <= 0.1 and avg_d <= 5.0
        ok &= passed
        rows.append(
            {
                "horizon": h,
                "signals_v1": int(ga.loc[h, "signals"]),
                "signals_v2": int(va.loc[h, "signals"]),
                "signals_equal": sig_eq,
                "count_v1": int(ga.loc[h, "count"]),
                "count_v2": int(va.loc[h, "count"]),
                "count_equal": cnt_eq,
                "win_diff_pp": round(win_d, 4),
                "avg_diff_bps": round(avg_d, 2),
                "PASS": passed,
            }
        )
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    print(f"elapsed: {elapsed:.0f}s")

    OUT.write_text(
        "# M2 Gate Report — KDJ J<0 全市场 parity（v1 原样宇宙重放）\n\n"
        f"- 黄金参照：`{GOLDEN}`（v1 引擎，{len(universe)} 符号，2015–2024）\n"
        "- v2 口径：kdj_oversold(sma_mode=simple, J<0) → t+1 开盘 → close(entry+h)；"
        "entry_filters=none（复刻 v1 无过滤）\n"
        "- 判定：count 逐 horizon 相等、胜率 ≤0.1pp、均值 ≤5bps\n\n"
        + table.to_markdown(index=False)
        + f"\n\n运行耗时：{elapsed:.0f}s；复现命令：`python scripts/m2_gate_parity.py`\n\n"
        "宇宙说明：v1 的 PG securities 把 2,393 个非股票资产（含 sh110xxx 可转债、B股、"
        "板块指数等）误分类为股票并纳入了研究；v2 生产宇宙（TASK-011 修正后）不含它们。"
        "本 gate 以 v1 原样清单重放以隔离引擎等价性；生产研究一律使用修正后的股票宇宙。\n"
    )
    print(f"report -> {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

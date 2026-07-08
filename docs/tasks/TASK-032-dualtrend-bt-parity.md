# TASK-032: DualTrend bt 策略移植 + 历史报告 parity（M3 gate 卡）

- Milestone: M3　|　State: backlog
- Branch: `task/TASK-032-dualtrend-bt-parity`　|　Depends: TASK-031

## Context
`docs/backtest_platform.md` §5 M3 gate：DualTrend 呼吸策略在 v2 Backtrader 栈重跑，对照黄金参照 `docs/parity/dualtrend_breath_full_20260224_220316_summary.csv`（来源见 `docs/parity/README.md` 行 9；J13/VR3.5 等 v1 默认参）。**换引擎不许换结论**。v1 源码参照（已在 TASK-004 删除，从历史读）：
```bash
git show 53f72fd^:src/quant/backtest/strategies.py   # DualTrendBreathStrategy（含 filter_untradable 三旗标过滤）
git show 53f72fd^:src/quant/backtest/engine.py       # run_dualtrend_breath_backtest 默认参数=黄金参照口径
git show 53f72fd^:src/quant/data/loader.py           # v1 feed 字段与复权口径
```

## Goal
`myquant backtest dualtrend configs/backtest/dualtrend_parity.yaml` 重跑全量 → 汇总表对照黄金 CSV：**样本数完全一致、胜率差 ≤0.1pp、均值差 ≤5bps**（M2 gate 同款判据）；超差逐项书面解释，禁止静默放宽。

## Scope
```python
# src/quant/backtest/dualtrend.py
class DualTrendBreathStrategy(bt.Strategy):
    """v1 逐条移植：参数名/默认值与 53f72fd^ 版本一致（short_period=10, m1/m2/m3/m4=14/28/57/114,
    vol_window=30, vol_ratio=3.5, use_double_vol, setup_window=20, require_bullish_setup,
    kdj_n/k/d=9/3/3, j_low=13.0, entry_mode="j_or_zone", entry_require_trend,
    entry_require_activity, require_pullback, filter_untradable, horizons=(1,3,5,10,20)）。
    不可成交过滤用 TASK-031 AShareConstraints/feed 旗标实现，语义对齐 v1
    （信号日与入场日的 suspended/一字涨停检查，见 v1 _entry_blocked_today/_signal_blocked_prev）。"""

def run_dualtrend_backtest(config_path: str | Path) -> dict[str, Path]:
    """yaml(symbols/universe, start/end, 全部策略参数, parity_mode) → 逐符号 cerebro →
    horizon 前向收益汇总（v1 get_stats 口径）→ quant.reporting.report 出 <prefix>_summary.{csv,md}。"""
```
- CLI：`myquant backtest dualtrend <cfg>`（挂 TASK-030 建的 backtest 子 app；若 030 未合并则本卡自建，冲突方后合并者 rebase）。
- `configs/backtest/dualtrend_parity.yaml`：固化 v1 全量运行口径（universe=exclude star、区间、默认参数），文件头注释注明黄金 CSV 文件名。
- **parity_mode 开关**：v1 的 KDJ/均线语义按 53f72fd^ 源码逐条复刻（若 v1 用 bt.indicators 简单均线，parity 模式必须 sma 口径——参照 M2 的教训：v1 KDJ=简单均线而非 TDX 递归）；生产模式走 `quant.indicators` TDX 实现。两模式 config 切换，parity 验收只认 parity_mode。
- 对照脚本：`scripts/compare_parity.py <run_summary.csv> <golden.csv>` 输出逐行差异与判据结论（如 M2 已有同类脚本则复用）。

## Non-goals
策略优化/调参（R1 已裁定）；组合级回测；费用敏感性分析（黄金参照无费用口径，parity 同口径）；AMV regime 开关。

## Files to touch
`src/quant/backtest/dualtrend.py`, `src/quant/backtest/__init__.py`, `src/quant/cli.py`, `configs/backtest/dualtrend_parity.yaml`, `scripts/compare_parity.py`（如新建）, `tests/unit/test_dualtrend_bt.py`。

## Acceptance criteria
1. `pytest -q tests/unit/test_dualtrend_bt.py`：合成数据上策略信号点位与预期一致；filter_untradable 三场景（信号日停牌/入场日停牌/入场日一字涨停）样本被剔除。
2. 10 股小样本 parity：黄金 CSV 若无逐符号行则用全量判据的缩样冒烟（跑通 + 汇总表结构一致）。
3. 全量：`myquant backtest dualtrend configs/backtest/dualtrend_parity.yaml` 跑通（耗时记 STATUS 备注），`scripts/compare_parity.py` 输出：signals/count 完全一致、win_rate ≤0.1pp、avg_return ≤5bps，结论 PASS。超差 → 不许改容差，把逐项差异分析写进 STATUS 备注并置 review。
4. `pytest -q -m "not integration"` + `ruff check .` 全绿。

## Notes / risks
- **数据口径是最大风险**：v1 跑在 PG qfq（TDX 减法式）上，v2 是乘法 hfq/qfq（data_platform.md §6）。KDJ/均线对复权方式敏感度低但非零；若对不齐先查复权口径再查指标语义（M2 gate 时 KDJ parity 已趟过一遍，参照 `configs/study_kdj_j0_parity.yaml` 与 TASK-025 review 的处理）。
- 黄金 CSV 的 `signals=42637, count(h1)=42568` 差值来自 horizon 尾部截断——对照时按 horizon 逐行比。
- 本卡是 M3 gate 的三报告之一（016/025/032），PASS 后才轮到 TASK-033。

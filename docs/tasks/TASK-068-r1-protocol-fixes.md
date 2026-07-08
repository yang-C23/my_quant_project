# TASK-068: R1 协议一致性修复 — 配对交易入场严格 t+1 + 探索卡 ashare 过滤

- Milestone: R1（收官后修正）　|　State: backlog
- Branch: `task/TASK-068-r1-protocol-fixes`　|　Depends: TASK-067

## Context
R1 收官后复审确认两处偏离 `docs/research/PLAN.md` §1 的 Tier1 协议（t 信号 → t+1 开盘入场，停牌/一字板样本**剔除**而非顺延）：

1. `src/quant/research/trade_pairs.py::run_pair_study`（L61）入场用 `_next_tradable_pos(bars, signal_pos+1)`，t+1 停牌/open 缺失时**顺延到下一可交易日入场**——协议要求剔除。影响 TASK-063/064 的 IS 结果与审查者 OOS 脚本（同引擎）。
2. `src/quant/research/exploratory.py`：`_load_prices` 只载 open/close（无 raw_open/is_suspended/limit_up_price），`_top_quantile_event` 传 `entry_filters="none"`——top_h5_avg / top_h5_profit_factor 未按协议过滤。IC/分层判定列不受影响，但 065 留档 M6 的 washout/turnover_cost 数字必须协议合规。

参照实现：`src/quant/research/forward_returns.py::run_event_study`（严格 t+1，`entry_suspended`/`entry_limit_up` 分桶剔除）——修复即对齐该口径。

## Goal
`run_pair_study` 与 065 top 分位事件研究完全符合 PLAN.md §1；063/064/065 三份 IS 报告按同配置复跑，findings 增补修复后差异；预期结论方向不变。

## Scope
1. `run_pair_study` 入场侧改严格 t+1（对齐 forward_returns 命名与分桶）：
   - `entry_pos = signal_pos + 1`；越界 → `exclusions["entry_missing"]`；
   - `entry_filters="ashare"`：t+1 `is_suspended` 或 open NaN → 新增 `exclusions["entry_suspended"]`；一字涨停开盘（raw_open ≥ limit_up_price）→ `exclusions["entry_limit_up"]`（替换现 `entry_filtered` 键名）；
   - `entry_filters="none"`：open NaN → `entry_missing`，其余照收（parity 语义）。
   - **出场侧不改**：`_exit_trade` 里 `_next_tradable_pos` 顺延复牌后首个可交易日开盘卖出是持仓者的真实语义，**有意保留**——不要顺手"统一"掉。
2. exploratory：`_load_prices` 改为 qfq(open,close) + raw(open→raw_open, suspended→is_suspended, limit_up_price) join（照抄 `forward_returns._load_one_price` 口径，TASK-067 合并后应走 batch API）；`_top_quantile_event` 改传 `entry_filters="ashare"`。
3. 复跑三份 IS 报告（配置不动，同 800 股 seed=42 样本，隔离协议修复的净效应）：
   `myquant research configs/research/dual_trend.yaml` / `shortterm.yaml` / `exploratory.yaml`。
4. `docs/research/findings/TASK-063.md`、`TASK-064.md`、`TASK-065.md` 各加一节"2026-07 协议修复后复跑"：新旧关键数字并排（trades 数、profit_factor、笔均、中位数；065 为 top_h5_avg/PF）+ 一句结论是否翻转。

## Non-goals
不重开参数搜索；不碰 OOS（审查者复核时自行重跑）；不改 forward_returns；不改配置。

## Files to touch
`src/quant/research/trade_pairs.py`, `src/quant/research/exploratory.py`, `tests/unit/test_trade_pairs.py`, `tests/unit/test_exploratory_factors.py`, `docs/research/findings/TASK-063.md`, `docs/research/findings/TASK-064.md`, `docs/research/findings/TASK-065.md`。

## Acceptance criteria
1. `pytest -q tests/unit/test_trade_pairs.py`：新增用例——(a) t+1 停牌合成序列：样本剔除且计入 `entry_suspended`（防倒退回顺延）；(b) t+1 一字涨停开盘 → `entry_limit_up`；(c) 持仓中停牌 → 出场顺延至复牌开盘（守护出场语义不被误改）。
2. `pytest -q tests/unit/test_exploratory_factors.py`：top 分位事件研究在含停牌/一字板的合成数据上剔除对应样本。
3. 三条 `myquant research` 命令跑通出报告；三份 findings 的增补节存在且含新旧对照表。
4. `pytest -q -m "not integration"` + `ruff check .` 全绿。

## Notes / risks
- **预期结论方向不变**（063 无退出规则胜原版死叉；064 候选表微调；065 全部未过门槛）。若任何一张卡结论**翻转**：停止，置 review 并在 STATUS 备注写明，等规划者裁定（可能需重开 R1 裁定，不许自行改结论文字）。
- 顺延→剔除会减少 trades 数（t+1 停牌样本占比预计 <1–2%），比较时看方向与量级，不追求逐位。
- 审查者将用同引擎重跑 OOS 裁定脚本核对 R1-final-report 数字是否需要勘误。

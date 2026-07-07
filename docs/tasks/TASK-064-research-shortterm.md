# TASK-064: 研究 — 单针/砖形短线参数（持有期 × 止损）

- Milestone: R1　|　State: backlog
- Branch: `task/TASK-064-research-shortterm`　|　Depends: TASK-063（复用 trade_pairs）

## Context
docs/indicators/brick.md 执行规则（2–4 日爆发、止损=买入 bar 低点、两日不拉就走）、volume_patterns.md 单针代理（先验 胜率37%/盈亏比3:1）。

## Goal
IS 段内为 brick 三变体与 single_needle_proxy 找到 持有期 × 止损 的稳健组合；检验笔记先验是否成立。

## Scope
1. 复用 `run_pair_study`：entry ∈ {brick_strict, brick_relaxed, brick_len, single_needle_proxy}；
   exit 网格：max_hold ∈ {1,2,3,4,6} × stop ∈ {买入bar低点, −2%, −3%, 无}；外加"两日未脱离成本价即走"规则（`close(entry+2) <= open(entry)` 触发次日出场）。
2. 笔记先验对照：单针代理的（胜率, 盈亏比）与 (37%, 3:1) 的偏差及显著性（bootstrap CI）。
3. 砖形补充维度：`smallup_pct ∈ {0.02,0.03,0.04}`（涨幅上限是笔记强调的"没爆发过"关键）。
4. `configs/research/shortterm.yaml` + `docs/research/findings/TASK-064.md`（分 regime；候选 ≤2 组/指标）。

## Non-goals
尾盘 vs 次日开盘的入场时点差异（日线数据无法区分，注明局限）；20cm 创业板单独规则（笔记明确未回测过，剔除 gem 跑一版对照即可）。

## Files to touch
`configs/research/shortterm.yaml`, `tests/unit/`(如 trade_pairs 需扩展则同步), `docs/research/findings/TASK-064.md`。

## Acceptance criteria
1. 复现命令跑通、findings 数字可复现（IS）。
2. findings 含：四 entry × 持有/止损网格矩阵、笔记先验对照（含 CI）、gem 剔除对照、候选清单。
3. ruff/全套绿；无 2022+ 数字。

## Notes / risks
短线信号对涨跌停敏感——ashare 过滤已剔一字板入场，但止损在跌停日无法成交：trade_pairs 的止损执行需顺延到可成交日（TASK-063 若未覆盖此规则，本卡补上并加测试）。

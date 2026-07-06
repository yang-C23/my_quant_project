# TASK-016: PG 黄金对齐验证 `scripts/validate_vs_pg.py`

- Milestone: M1　|　State: backlog
- Branch: `task/TASK-016-validate`　|　Depends: TASK-013（014 可并行）

## Context
ADR-0002 迁移安全网；data_platform.md §6（判定标准与 QFQ 公式差异声明）。这是 M1 gate 的核心工具：换存储不许换数据。

## Goal
一条命令产出新旧管线全量对齐报告（markdown），0 硬失败才算 M1 通过。

## Scope
```python
# scripts/validate_vs_pg.py  （一次性运维脚本，允许 import quant.*；M3 随 PG 删除）
# 用 psycopg2 直连 settings.pg_dsn（docker start pg_quant 由运行者负责）
检查项（全量，逐符号分块流式，不允许抽样）：
  C1 日历：qlib calendars/day.txt == PG 交易日全集（daily_kline distinct date）
  C2 符号集：staging securities == PG tdx.securities（symbol 集合差集为空）
  C3 行数：每符号 staging 行数 == PG 行数
  C4 原始 OHLCV+amount+volume：逐值完全相等（float 用 ==，因两边同源 TDX；容忍 1e-9 绝对差）
  C5 hfq_factor：rtol ≤ 1e-6；hfq 价（raw*factor vs PG v_hfq_daily）rtol ≤ 1e-6
  C6 qfq：与 PG v_qfq_daily 相对差 >0.5% 的行计入 WARNING（预期存在，公式差异见 data_platform §6）
  C7 instruments 区间：list/delist 与 PG 首末交易日一致
输出：docs/reviews/M1-validate-vs-pg.md（各项 PASS/FAIL/WARN + 违例明细 top50 + 汇总统计）
CLI：myquant validate（薄封装调本脚本）
```

## Non-goals
修数据（只报告）；性能优化到极致（全量跑 ≤ 20 分钟即可）。

## Files to touch
`scripts/validate_vs_pg.py`, `src/quant/cli.py`, `tests/unit/test_validate_helpers.py`。

## Acceptance criteria
1. `pytest -q tests/unit/test_validate_helpers.py` 全绿：比较函数对合成数据的注入错误（改一个 close、删一行、扰动 factor 1e-4）全部被正确捕获并归入对应检查项。
2. 集成（审查者，= M1 gate）：`docker start pg_quant && myquant validate` → 报告 C1–C5、C7 全 PASS，C6 仅 WARN。
3. `ruff` 全绿。

## Test plan
如上；PG 不可达时报错信息明确（提示 docker start）。

## Notes / risks
- PG 自本卡合并起**冻结**（不再运行任何 v1 写入脚本）——审查者在 gate 报告中记录冻结时间与 PG 末日期。
- 两边"最后交易日"可能差 1 天（PG 冻结后 v2 又更新过）→ 比较窗口截断到 `min(pg_max_date, v2_max_date)`，报告注明。
- 0 价停牌行的处理差异（v1 导入时是否过滤）先查 PG 实况再定容差，结论写进报告。

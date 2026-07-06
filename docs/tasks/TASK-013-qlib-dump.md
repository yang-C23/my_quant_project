# TASK-013: staging → qlib bin（calendars / instruments / features）

- Milestone: M1　|　State: backlog
- Branch: `task/TASK-013-qlib-dump`　|　Depends: TASK-012

## Context
data_platform.md §5（qlib 约定：$close=hfq 复权价、$factor、扩展字段、instruments PIT 区间）。ADR-0002。

## Goal
`myquant dump cn-daily` 从 staging 全量重建 `DATA_ROOT/qlib/cn_daily`，qlib 原生 API 可读且数值正确。

## Scope
```python
# src/quant/etl/qlib_dump.py
def build_calendar(staging_dir: Path) -> list[pd.Timestamp]      # 全 daily 日期并集，升序
def build_instruments(staging_dir: Path, out_dir: Path) -> None  # all.txt + nostar.txt + main_only.txt
def dump_cn_daily(staging_dir: Path, qlib_dir: Path) -> DumpStats
    """features 字段：open,high,low,close,volume（=原始值×hfq_factor；volume 除以 factor——qlib 惯例，
    保证 价×量 守恒）、factor、amount、turnover、float_mktcap、total_mktcap、
    st、suspended、limit_up、limit_down（0/1）、limit_up_price、limit_down_price。
    实现方式：优先复用 qlib 官方 dump_bin 逻辑（vendor 其 DumpDataAll 单文件进
    src/quant/etl/_qlib_dump_vendor.py 并注明来源版本），避免 bin 格式漂移。"""
```
- CLI：`myquant dump cn-daily [--symbols sh600000,…]`（symbols 子集用于调试）。

## Non-goals
增量 dump（TASK-015）；us/1min region（M5）。

## Files to touch
`src/quant/etl/qlib_dump.py`, `src/quant/etl/_qlib_dump_vendor.py`, `src/quant/cli.py`, `tests/unit/test_qlib_dump.py`, `tests/fixtures/staging_mini/**`(由 fixture .day 经 TASK-010/012 流程生成的迷你 staging，<150KB，生成脚本注明)。

## Acceptance criteria
1. `pytest -q tests/unit/test_qlib_dump.py` 全绿：迷你 staging → dump 到 tmp_path → `qlib.init(provider_uri=tmp)` → `D.features(["SH600000"],["$close","$factor","$volume"])` 与 staging 手算复权值 rtol ≤ 1e-6 对齐；calendar 与 instruments 文件内容逐行断言。
2. 集成（审查者）：全量 dump ≤ 5 分钟；`D.features` 抽查 3 符号（含一只退市股）与 staging 对齐；`D.instruments("nostar")` 不含 688/689 开头。
3. `ruff` 全绿。

## Test plan
如上；退市股 instruments 区间断言（end=末交易日）；qlib float32 精度损失纳入容差考量（bin 为 float32 → 对齐用 rtol 1e-6 而非 1e-9）。

## Notes / risks
- **qlib CN 惯例**：$open/$high/$low/$close 均为复权价，$volume=raw_volume/factor，raw 价 = $close/$factor。全下游（data.api、看板）都按此约定还原。
- instruments 日期格式 `SH600000\t1991-04-03\t2026-07-04`（tab 分隔）。
- 0 价/停牌行：dump 前以 staging 原样写入，NaN 语义由 qlib 对齐日历时自然产生——不要在 dump 层填补。

# TASK-015: 增量日更 `myquant update`（tail-read，幂等）

- Milestone: M1　|　State: backlog
- Branch: `task/TASK-015-update`　|　Depends: TASK-013

## Context
data_platform.md §2（日更 tail-read 直读 /mnt/d 可接受）§5（qlib 增量）。v1 `scripts/update_daily.py` 的教训：全文件重读 + `or True` 强制全量重算 → 15–30 分钟；v2 设计目标 ≤ 60 秒（无新数据 ≤ 10 秒）。

## Goal
TDX 客户端盘后下载数据 → `myquant update` 一条命令完成 staging 追加 + 衍生增量 + qlib 追加；**幂等**。

## Scope
```python
# src/quant/etl/update.py
def read_day_tail(path: Path, n_records: int) -> bytes           # seek(-n*32, SEEK_END)，短文件回退全读
def collect_new_rows(tdx_home: Path, last_date: pd.Timestamp, *, margin: int = 5) -> pd.DataFrame
    """n_records = 日历缺失天数 + margin；解析后过滤 date>last_date。直接读 /mnt/d（串行）。"""
def apply_update(staging_dir: Path, qlib_dir: Path, new_rows: pd.DataFrame) -> UpdateStats
    """1) daily 追加（新分区文件 append，不重写历史）；2) GBBQ 全量重解析对比，有变化才重算受影响符号；
    3) 仅对**有新行/新事件的符号**重算 basics/adjust/flags 并覆写该符号切片；
    4) qlib 增量追加（calendar 追加新日期、features 追加，语义对齐 qlib DumpDataUpdate）；
    5) new_rows 为空且 GBBQ 无变化 → 记录日志后直接返回（**禁止任何重算**——v1 `or True` 之鉴）。"""
```
- CLI：`myquant update [--dry-run]`；`--dry-run` 只打印将追加的行数/符号数。

## Non-goals
回填历史缺口（重跑 `etl full` 解决）；美股更新。

## Files to touch
`src/quant/etl/update.py`, `src/quant/cli.py`, `tests/unit/test_update.py`, `tests/integration/test_update_real.py`。

## Acceptance criteria
1. `pytest -q tests/unit/test_update.py` 全绿：
   - tail-read 短文件/长文件/恰好边界；
   - 迷你 staging 截断末 3 日 → update → 与未截断黄金版逐值一致（含 adjust/flags 重算正确）；
   - **幂等**：紧接着再跑一次 → `UpdateStats.new_rows == 0` 且所有 parquet/bin 内容 hash 不变；
   - GBBQ 无变化时 adjust 不被触碰（mtime/hash 断言）。
2. 集成（审查者）：真实环境 `myquant update` 二连跑，第二次 ≤ 10 秒且 0 新行。
3. `ruff` 全绿。

## Test plan
如上；日历边界（周一更新补周五）、新股（staging 无此符号）路径。

## Notes / risks
- qlib bin 追加需与 calendar 索引严格对齐（bin 首 float 为日历起始索引）——复用 vendor dump 的 update 路径，勿手搓偏移。
- 除权发生在增量窗口时 hfq 全历史因子会变 → 该符号 adjust+features 必须整段重写（不是只追加尾巴）；测试覆盖此用例。

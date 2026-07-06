# TASK-010: TDX 镜像 + 并行解析 → staging daily Parquet

- Milestone: M1　|　State: backlog
- Branch: `task/TASK-010-staging-daily`　|　Depends: TASK-003

## Context
data_platform.md §2（9P 规则）§3（.day 格式）§4（daily schema）。v1 解析器 `src/quant/etl/tdx_parser.py` 算法正确但逐条 unpack 且串行。

## Goal
`myquant etl full --steps daily` 在本机全量（~12000 文件，28M+ 行）完成镜像+解析+落盘 ≤ 5 分钟。

## Scope
```python
# src/quant/etl/mirror.py
def mirror_vipdoc(tdx_home: Path, mirror_dir: Path) -> MirrorStats:
    """tar 管道批拷 vipdoc/sh|sz|bj 的 lday 目录到本地 ext4；返回文件数/字节数/耗时。"""

# src/quant/etl/staging.py
DAY_DTYPE = np.dtype([...])  # <IIIIIfII，见 data_platform.md §3
def parse_day_bytes(buf: bytes, symbol: str) -> pd.DataFrame: ...   # np.frombuffer 向量化，价格/100
def build_daily_staging(mirror_dir: Path, staging_dir: Path, *, workers: int = 20) -> StagingStats:
    """ProcessPoolExecutor 并行解析 → 按 exchange 分区写 staging/daily/，(symbol,date) 排序，
    zstd 压缩；日期非法/文件损坏 warn+跳过并计入 stats。含指数（sh999xxx/sz399xxx）。"""
```
- `src/quant/cli.py` 增加 `etl full --steps daily`（steps 逗号分隔，本卡只实现 daily，其余 step 报 NotImplemented）。
- `tdx_parser.py` 重构为向量化版本，保留 `generate_symbol`/文件收集逻辑；旧逐条 API 删除。
- Fixtures：`tests/fixtures/tdx/lday/{sh600000,sz000001,sh999999}.day`（各截取前 ~200 条真实记录，单文件 <8KB；生成命令写进 fixtures/README.md）。

## Non-goals
GBBQ/证券/板块（TASK-011）、衍生表（011/012）、qlib dump（013）、增量（015）。

## Files to touch
`src/quant/etl/{mirror.py,staging.py,tdx_parser.py}`, `src/quant/cli.py`, `tests/unit/test_staging.py`, `tests/fixtures/tdx/**`, `tests/fixtures/README.md`。

## Acceptance criteria
1. `pytest -q tests/unit/test_staging.py`：fixture 字节 → 已知 OHLCV 黄金值（与 v1 解析器输出交叉核对过）逐值相等；损坏记录被跳过且计数正确。
2. `ruff check .` 全绿。
3. 集成（审查者跑）：`myquant etl full --steps daily` 后
   `python -c "import duckdb; print(duckdb.sql(\"select count(*), count(distinct symbol) from read_parquet('$DATA_ROOT/staging/daily/*/*.parquet')\"))"` 行数 ≥ 28,000,000、符号数 ≈ 12,000；耗时打印 ≤ 5 分钟。

## Test plan
单测全部走 fixture + tmp_path；并行 worker 数在测试中设 2。

## Notes / risks
- worker 内只读**镜像**路径，禁止 `/mnt/d`（data_platform §2）。
- Windows 路径反斜杠兼容（v1 import_tdx 有处理逻辑可参考）。
- 价格为 0 的记录（停牌残留）保留原样，由 flags（TASK-011）处理，不在解析层过滤。

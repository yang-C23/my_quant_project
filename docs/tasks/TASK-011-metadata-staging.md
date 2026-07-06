# TASK-011: GBBQ / 证券主表 / 板块 / 日历 / 标志位 → staging

- Milestone: M1　|　State: backlog
- Branch: `task/TASK-011-metadata`　|　Depends: TASK-010

## Context
data_platform.md §4（securities/gbbq/blocks/holidays/flags schema）。解码器 `src/quant/etl/gbbq.py` 与 `blocks.py` 算法沿用 v1（已验证），本卡负责向量化落盘与衍生。

## Goal
`myquant etl full --steps meta` 产出 securities/gbbq/blocks/holidays/flags 五张 staging 表。

## Scope
```python
# src/quant/etl/staging.py 追加
def build_gbbq_staging(tdx_home_or_mirror: Path, staging_dir: Path) -> int          # 解密→gbbq.parquet
def build_securities_staging(staging_dir: Path) -> int
    """由 daily 的 symbol 全集推导：exchange/sec_type/board（前缀规则沿 v1 SQL regex 的语义），
    list_date/delist_date = 每符号首/末交易日（末日 < 全局末日-20个交易日 视为退市）。"""
def build_blocks_staging(tdx_home_or_mirror: Path, staging_dir: Path) -> int        # blocks+holidays
def build_flags_staging(staging_dir: Path) -> int
    """is_suspended：符号在交易日历上有日期缺口的日子（对齐日历后 reindex 判空）；
    is_st：当前 ST/风险警示板块成员（快照，非 PIT——局限性写注释与文档）；
    limit_up/down_price：round(preclose×(1±ratio),2)，ratio 按 board（主板10%/创业科创20%/北证30%/ST 5%）；
    is_limit_up/down：close==limit 价。依赖 basics.preclose（TASK-012 输出）——因此本函数由 CLI 在
    adjust/basics 之后调用；卡内先实现并用合成 preclose 测试。"""
```
- CLI `etl full` 串起 steps：`daily → gbbq → securities → blocks → (adjust/basics: TASK-012) → flags`。

## Non-goals
adjust/basics 计算本体（TASK-012）；qlib dump（013）。

## Files to touch
`src/quant/etl/{staging.py,gbbq.py,blocks.py}`, `src/quant/cli.py`, `tests/unit/test_metadata_staging.py`, `tests/fixtures/tdx/gbbq_sample.bin`(若可截取；否则用解码后 CSV fixture，生成法写 README)。

## Acceptance criteria
1. `pytest -q tests/unit/test_metadata_staging.py` 全绿（board 前缀分类表驱动测试：600/601/603/605→main-sh, 000/001/003→main-sz, 300/301→gem, 688/689→star, 43/83/87/920→bse, 999xxx/399xxx→index）。
2. 集成（审查者）：五表行数与 PG 对应表同量级（securities ~12K、gbbq ~180K、blocks_member ~77K）。
3. `ruff check .` 全绿。

## Test plan
GBBQ 解码：真实小样本或 v1 解码输出的 CSV fixture 对照；suspension：合成日历缺口用例；limit 价：ST/创业板/主板边界用例（含四舍五入到分）。

## Notes / risks
- ST 快照非 PIT 是**已知局限**（v1 亦无 ST 历史）；文档已声明，禁止悄悄"修复"。
- 北交所涨跌停 30% 且上市首日无限制——首日样本直接标 is_limit 计算不适用（NaN）。
- GBBQ category 语义沿 v1 解码器注释；只有 category=1 参与复权（TASK-012）。

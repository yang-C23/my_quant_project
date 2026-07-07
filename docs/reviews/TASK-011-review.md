# TASK-011 Review（第 1 轮）

- 日期：2026-07-07　|　开发者 & 审查者：Codex（自审；验收命令真实运行留痕）
- 分支：`task/TASK-011-metadata`

## 验收命令运行结果

| # | 命令 | 结果 |
|---|---|---|
| 1 | `pytest -q tests/unit/test_metadata_staging.py` | PASS（4 用例：GBBQ decoded fixture、证券前缀分类/退市推断、板块/成员/节假日解析、flags 停牌/ST/涨跌停合成场景） |
| 2 | `pytest -q -m "not integration"` | PASS（40 passed） |
| 3 | `ruff check .` + `ruff format --check .` | PASS |
| 4 | `myquant etl full --steps meta --no-mirror` | PASS：gbbq 182,295 行、securities 12,169 行、blocks/holidays 77,405 行；flags 因 TASK-012 的 basics 尚不存在而显式跳过 |

## 质量意见

- `securities` 由 daily 全量 symbol/date 推导，板块分类按卡面前缀表驱动覆盖：主板、创业板、科创板、北证、指数与 ETF。
- `gbbq`、`blocks`、`holidays` 复用既有 v1 解析器，只在 staging 层做 schema 化、去重、排序和 zstd parquet 落盘。
- `flags` 函数已完整实现并用合成 `basics.preclose` 测试；CLI 的 `meta` alias 在 TASK-012 前不会因缺 basics 硬失败，待 basics 表生成后会自动产出 flags。
- ST 标志仍是当前板块快照，非 PIT；这是卡面声明的已知局限，代码注释中保留。

## 结论

**PASS** —— TASK-011 可进入 review；后续 TASK-012 生成 basics 后需重跑 `myquant etl full --steps meta` 确认 flags 实表行数。

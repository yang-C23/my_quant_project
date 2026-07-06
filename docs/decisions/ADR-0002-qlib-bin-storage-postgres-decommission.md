# ADR-0002: 全面迁移 qlib bin 存储，PostgreSQL 退役；Parquet staging 作 ETL 中间层

- 状态：accepted（executed 待 M3 gate 后标记）
- 日期：2026-07-06
- 决策人：用户（明确选择"全面迁移 qlib bin"）+ 规划者

## Context

用户要求判断 qlib bin 格式 vs 数据库哪个更符合本框架的吞吐效率。分析结论：全市场横截面因子扫描上，qlib bin（按 instrument 列式二进制 + 内建表达式引擎）比逐符号 SQL 快 1~2 个数量级；分钟线（~3 亿行/年）对行式 PG 压力大。PG 的优势（元数据管理、即席 SQL、事务）可由 Parquet staging + DuckDB 以零常驻服务的方式覆盖大部分。

## Decision

- 唯一研究存储 = qlib bin（`DATA_ROOT/qlib/{cn_daily,us_daily,cn_1min}`）。
- ETL 中间层 = Parquet staging（无损原始 + GBBQ + 元数据 + 衍生表），DuckDB 即席查询。
- **迁移安全网**：现有 PG（docker pg_quant）自 M1 启动起冻结写入，作为黄金参照；`validate_vs_pg.py` 对齐（原始 OHLCV 全等 + hfq ≤1e-6 + 日历/区间一致）通过且 M3 gate 达成后，pg_dump 归档至 `DATA_ROOT/archive/`，容器与 `quant/db` 代码删除。
- 复权口径：v2 统一乘法 hfq（$factor 字段）；v1 PG qfq 视图为 TDX 减法式，历史差异为公式定义差异（见 data_platform.md §6）。

## Consequences

- 得到：研究吞吐、零数据库运维、qlib 工作流原生兼容、分钟线扩展路径清晰。
- 放弃：SQL 服务与已有 schema；即席查询改走 DuckDB-on-Parquet。
- 风险：迁移期数据错漏 → 以 PG 黄金门硬性拦截；qlib bin 不可人读 → staging 永久保留原始数据。

## Alternatives considered

- PG 主库 + qlib bin 缓存（规划者原推荐）：正确性最稳，但双存储双维护，用户选择了更简的单存储。
- Parquet+DuckDB 替代 PG 且不用 qlib bin：研究层仍需 qlib 格式，等于三套格式。

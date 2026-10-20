# 架构与模块边界

数据依赖顺序：来源原始证据 → 标准Parquet → 特征/账本/报告。
Qlib为可重建适配层，不能代替原始证据或现金账本。

| 模块 | 责任 |
|---|---|
| `quant.config`、`scripts/quant` | 运行配置、工作树源码与解释器入口 |
| `quant.etl.restart` | 元数据优先、逐证券全历史合并、修订重算、阶段恢复与原子发布 |
| `quant.data.snapshots/recovery` | 清单、哈希、发布、回滚、备份及隔离恢复演练 |
| `quant.data.catalog` | 来源版本、Arrow类型、年份分区、历史修订及as_of查询 |
| `quant.data.providers/derivatives` | 有限重试的外部适配器，保留原始字节，不隐藏接口变化 |
| `quant.data.quality/reconcile/audit` | 结构、单位、交叉来源、全部文件及历史产物盘点 |
| `quant.longterm.features/extensions` | 因果温度、恐慌、企稳、KDJ及定义明确的扩展代理 |
| `quant.longterm.ledger/engine/allocation` | Decimal现金、公司行动、资金计划、成交、独立配置与组合 |
| `quant.longterm.research` | 预登记、证据门、窗口、全实验留存和回放 |
| `quant.longterm.monitor` | 每日影子记录、依赖失败时暂停，不连接券商 |
| 原有`research/backtest/indicators` | 保留个股研究兼容能力，历史结果须重新验收 |

模块中的计算与IO尽量分离。原始不复权价格与公司行动分存；研究通过数据契约读取，
不依赖具体供应商列名。参数在配置，实验清单在注册文件，运行状态在看板及数据根目录。

CPU足以承担当前日频宽基回测，GPU不是数据正确性或稳定复利的保证。
本轮不为使用5090而加入未经验证的机器学习或复杂优化。

历史ADR保留；涉及“Qlib唯一存储”或旧模型角色的决定已被
[ADR-0006](decisions/ADR-0006-trusted-longterm-platform.md)取代。

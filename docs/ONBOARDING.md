# 接手入口

从任何agent、空白上下文或新工作树接手，按以下顺序执行。

1. 阅读 [AGENTS.md](../AGENTS.md)、[任务看板](tasks/STATUS.md)、[总计划](restart/MASTER_PLAN.md)及当前任务卡。
2. 检查 `git status --short --branch` 和 `git worktree list`，保留用户及其他工作树的修改。
3. 在仓库根目录执行 `scripts/quant doctor`。新环境先执行 `python3 scripts/bootstrap_env.py`；使用 `.env` 的数据路径。
4. 数据相关工作读 [数据契约](data_platform.md)，研究相关工作读 [研究协议](restart/RESEARCH_PROTOCOL.md)。
5. 在已授权任务分支实施。更新看板中的证据、缺口和下一步；已批准的总计划可连续推进多个阶段。
6. 提交前执行 `scripts/quant test`、`scripts/quant lint` 及当前阶段真实验收；记录实际输出。

## 事实源

| 问题 | 唯一正文/查询 |
|---|---|
| 当前阶段、未决问题 | `docs/tasks/STATUS.md` |
| 本轮全部范围 | `docs/restart/MASTER_PLAN.md` |
| 模块与依赖 | `docs/architecture.md` |
| 数据schema、单位、复权 | `docs/data_platform.md` |
| 资金、策略、绩效定义 | `docs/restart/RESEARCH_PROTOCOL.md` |
| 来源授权与适用边界 | `configs/data_sources.yaml`；证据解读 `docs/restart/DATA_SOURCES.md` |
| 冻结实验参数 | 原基线`configs/longterm.yaml`；主组`cash_pool.yaml`、扩展`cash_pool_extensions.yaml`、追加`current_price_pe.yaml`及`confirmation_horizon.yaml`；最终以各运行`registration.json`为准 |
| 运行、恢复、定时器 | `docs/restart/OPERATIONS.md` |
| 当前数据版本 | `DATA_ROOT/current.json` |
| 最新研究与告警 | `DATA_ROOT/research/latest.json`、`DATA_ROOT/monitor/latest.json` |
| 已计算结果与证据限制 | 新现金池`docs/restart/CASH_POOL_RESULTS.md`；旧价格诊断`docs/restart/RESULTS.md`，各自绑定冻结登记 |
| CPU/GPU实测与优化执行 | 独立`/home/yang/projects/quant_performance`工作树；其`docs/restart/PERFORMANCE_AUDIT.md`维护唯一性能正文，状态仍在本项目STATUS |
| 本轮机器可读验收 | `DATA_ROOT/audits/restart-acceptance-20261020.json` |

数据、研究和审计详细产物保存在仓库外的`DATA_ROOT`。不要从旧报告复制收益结论，
不要把“解析成功”理解为“数据已准入”，不要把影子监控的暂停信息解读为卖出建议。

目前所有新投资结论均需通过数据和研究门槛。20交易日影子运行必须按真实时间累计，
历史重放不计天数。费用和预算示例不是用户真实账户状态。

交接至少写明：分支/提交、解释器/源码位置、快照ID、配置与数据版本、已执行命令、
测试结果、未决门槛、下一条可执行命令。无需依赖某一模型或之前的聊天记录。

总计划各条要求的实现与剩余缺口见[交付映射](restart/DELIVERY_MATRIX.md)。

# 宽基与红利低波长期投资研究平台

Python、Parquet、DuckDB数据底座，包含可回滚通达信迁移、公开数据版本目录、
现金流账本、实验登记与每日影子监控。Qlib是兼容研究层；Backtrader用于独立成交核对。
本轮关注指数与ETF，不自动交易或购买数据。

任何agent从 [接手入口](docs/ONBOARDING.md) 开始；执行范围见
[总计划](docs/restart/MASTER_PLAN.md)，当前状态仅在 [任务看板](docs/tasks/STATUS.md) 维护。

本轮探索研究的阅读顺序：

1. [结果摘要](docs/restart/MORNING_REVIEW_20261021.md)：宽基与红利低波、买入/退出及等待成本。
2. [完整ETF研究](docs/restart/ETF_TOTAL_RETURN_RESULTS.md)：真实分红、实际买入后5/10年、全部正负结果。
3. [复现入口](docs/restart/REPRODUCING_ETF_RESEARCH.md)：冻结代码、配置、数据清单和命令。
4. [下一阶段优先级](docs/restart/PHASE_CLOSEOUT.md#下一阶段的有限工作)：渠道、风险预算、估值证据与运行验收。

仓库保存代码、配置、研究摘要和证据索引。原始行情、供应商文件、完整账户账本及本机凭据不随仓库分发；
重放真实研究需要按来源许可准备对应的冻结数据。离线单测使用仓库内的小型fixtures。

```bash
python3 scripts/bootstrap_env.py
scripts/quant doctor
scripts/quant test
scripts/quant lint
scripts/quant platform --help
```

每个工作树使用本地`.venv`及`scripts/quant`，不重新安装到其他工作树的共享editable入口。
本机环境已独立安装锁定依赖，完整版本记录与重建方式见 [操作手册](docs/restart/OPERATIONS.md)。
`.env`只设置本机路径与已有凭证，不提交真实账户秘密。

| 操作 | 命令 |
|---|---|
| 全项目、数据、旧成果盘点 | `scripts/quant platform audit` |
| 更新通达信并原子发布 | `scripts/quant update` |
| 公开数据采集 | `scripts/quant platform fetch-public` |
| 来源交叉核验 | `scripts/quant platform crosscheck` |
| 数据目录 | `scripts/quant platform sources` |
| 正式准入检查与实验登记 | `scripts/quant platform research` |
| 明确降级的价格探索 | `scripts/quant platform research --exploratory` |
| 每日影子记录 | `scripts/quant platform daily` |

数据未通过来源许可、历史可得性、复权、覆盖和成交核验时，正式研究与提醒保持暂停。
价格指数、ETF价格和含分红总回报不混用；没有计算出的收益不填写。
旧CLI仍可访问，但修改已封存数据的命令会被拒绝。旧个股研究仅作历史证据。

- [数据契约与复权公式](docs/data_platform.md)
- [固定研究协议](docs/restart/RESEARCH_PROTOCOL.md)
- [来源、授权与覆盖](docs/restart/DATA_SOURCES.md)
- [审计发现](docs/restart/AUDIT.md)
- [最新ETF结果与未通过项](docs/restart/ETF_TOTAL_RETURN_RESULTS.md)
- [旧价格研究与版本边界](docs/restart/RESULTS.md)
- [总计划交付映射](docs/restart/DELIVERY_MATRIX.md)
- [架构](docs/architecture.md)

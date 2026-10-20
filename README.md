# 宽基与红利低波长期投资研究平台

Python、Parquet、DuckDB数据底座，包含可回滚通达信迁移、公开数据版本目录、
现金流账本、实验登记与每日影子监控。Qlib是兼容研究层；Backtrader用于独立成交核对。
本轮关注指数与ETF，不自动交易或购买数据。

任何agent从 [接手入口](docs/ONBOARDING.md) 开始；执行范围见
[总计划](docs/restart/MASTER_PLAN.md)，当前状态仅在 [任务看板](docs/tasks/STATUS.md) 维护。

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
- [已计算结果与未通过项](docs/restart/RESULTS.md)
- [总计划交付映射](docs/restart/DELIVERY_MATRIX.md)
- [架构](docs/architecture.md)

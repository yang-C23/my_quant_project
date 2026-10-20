# AGENTS.md — 共同工作契约

任何 agent 从 `docs/ONBOARDING.md` 冷启动。当前工作由用户批准的
`docs/restart/MASTER_PLAN.md` 和 `docs/tasks/TASK-080-trusted-index-restart.md` 定义。
`docs/tasks/STATUS.md` 是唯一任务状态源。旧任务及研究记录保留。

## 环境与命令

使用本工作树的 `scripts/quant` 入口；它固定源码路径并校验实际导入位置，
不修改其他 worktree 的 editable install。解释器通过 `QUANT_PYTHON` 配置。
运行时数据路径经 `.env` / `quant.config.Settings` 读取，src 内不硬编码用户路径。

```bash
scripts/quant doctor
scripts/quant --help
scripts/quant test
scripts/quant lint
```

## 工作流程

1. 读取计划、任务状态和相关数据/研究契约，确认分支及已有修改。
2. 在任务分支实施；用户明确授权的总计划可包含连续阶段，无需每阶段重复请求授权。
3. 每阶段记录命令、证据、结果和未决事项；未通过的数据不能进入正式投资结论。
4. 关键金融逻辑用手算样例和独立实现核对；记录审查方式，不冒称独立人员审查。
5. 保留其他 worktree 和用户修改；不自动合并主分支、推送、交易、购买数据或发送外部消息。

## 数据与研究红线

- 标准层为版本化 Parquet；原始证据、公司行动、修订和来源另存，Qlib 为可重建适配层。
- 数据变更经可审计CLI；先生成新快照并验收，再切换，保留回滚。
- date 是交易所本地交易日；available_at / retrieved_at 是UTC时间戳。
- 信号仅使用决策时已发布数据；最早下一可交易时点成交，不用未来成交情况反选信号。
- 分清原始价、复权价、价格指数、全收益指数、ETF净值和成交价格。
- 入金不是收益；应收股息不是可用现金；费用与分红不得重复计算。
- 来源许可、质量或历史可得性未通过时，降级探索；正式提醒输出暂停评估。
- 不把回溯指数当真实ETF历史，不把OI/成交量代理当净Gamma或爆仓事实。
- 不用最终样本外再次调参；保留全部实验及失败。

## 质量与交接

Python >=3.10，src布局，类型注解与简短docstring；指标计算与IO分离。
单测不联网，只用小型fixtures/tmp_path；真实ETL与研究作为显式验收执行。
不提交大数据或秘密；详细运行产物位于DATA_ROOT，文档保存摘要和复现入口。
提交前运行lint、相关测试、路径及任务范围检查。
交接更新任务状态、实际快照、运行命令、阻塞原因及下一步。

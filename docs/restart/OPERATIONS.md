# 运行、恢复与接手手册

状态与未完成事项以[任务看板](../tasks/STATUS.md)为准。本文件仅维护运行命令。
仓库工作目录为`/home/yang/projects/my_quant_project`，实际数据路径由`.env`和Settings读取。
默认数据目录为`/home/yang/quant_data`，凭证不要写入文档或提交。

## 环境

```bash
python3 scripts/bootstrap_env.py
scripts/quant doctor
scripts/quant test
scripts/quant lint
```

当前`.venv`关闭system-site-packages，已独立安装202项锁定依赖；不复用其他worktree的editable安装。
`requirements-lock.txt`保存Python3.10的依赖闭包，`requirements-runtime.txt`保留直接依赖说明。
新增/升级依赖需先验证兼容性，再运行`.venv/bin/python scripts/lock_environment.py`生成新锁，
重新测试并登记环境版本。doctor发现版本不符会返回非零；不要静默忽略。
离线测试当前上游MLflow有两项Pydantic弃用警告，依赖迁移前应跟踪，不影响本轮已通过行为。

## 数据更新与验收

```bash
scripts/quant platform audit
scripts/quant platform tdx-update --workers 4
scripts/quant platform sources
scripts/quant platform fetch-public
scripts/quant platform fetch-public --baostock
scripts/quant platform fetch-etf-day 2026-10-19
scripts/quant platform fetch-derivatives --month 202609 --year 2025
scripts/quant platform crosscheck
```

`scripts/quant update`为快照更新兼容入口。`update --dry-run`只是旧“新日期行数下界”预演，
不统计历史修订，不能作为完整更新清单。实际更新先冻结原始日线与元数据，逐证券读取全历史，
最新vipdoc覆盖同日旧基线，补洞、隔离异常、重算派生和Qlib，再验收并原子切换。
读取Windows大文件先顺序镜像到WSL本地；同步通达信软件完成后再采集。

`DATA_ROOT/current.json`是活动快照指针。快照中的`manifest.json`包含所有文件SHA256与来源/代码指纹；
`progress.json`记录已完成步骤，`quality.json`记录全量结构检查。
已封存快照不能由旧ETL写接口修改。相同来源和相同解析代码重复更新只记录比较证据，不重复发布。

公开源每个数据集独立锁、不可变原始响应、版本manifest与原子latest指针；
标准Parquet按市场/年份分区并ZSTD压缩。HTTP有重试和响应体限制，BaoStock客户端由90秒子进程超时保护。
服务失败不覆盖最近成功版本；后续监测按新鲜度与验收门决定暂停。`fetched`不等于正式研究通过。
Tiingo接口因长期留存条款门关闭，新增token不会自动授权采集；未购买任何数据。

`source_reports/crosscheck.json`汇总差异，另有逐条差异与覆盖缺口Parquet。
跨来源相同不能证明一手正确；当日ETF匹配不认证完整历史公司行动。

## 中断、回滚与备份

```bash
scripts/quant platform tdx-update --resume 未封存快照ID --workers 4
scripts/quant platform verify 快照ID
scripts/quant platform activate 快照ID
scripts/quant platform activate legacy
scripts/quant platform backup 快照ID
```

恢复只接受相同解析/派生代码指纹，沿用该次冻结原始输入，不重新偷偷换成外部最新数据。
源文件/算法改变时启动新构建；源校验或质量不通过则不发布。单发布者锁阻止并发更新。
`activate legacy`恢复原始目录；恢复新快照前会校验所有内容，缺失/损坏/额外文件均拒绝。
回滚数据后旧研究仍绑定原快照，不会被自动改写。

backup命令先校验原快照，生成TAR与哈希回执，并默认执行完整隔离恢复、发布和回滚演练。
重复备份已存在同名归档会拒绝覆盖。恢复目录与活动数据分离。
本机备份已实测，但不是异地灾备；跨磁盘/异地副本与定期恢复仍在维护待办中。

## 研究与重放

```bash
scripts/quant platform research
scripts/quant platform research --exploratory
scripts/quant platform research --exploratory --replay-run /完整路径/原研究目录
```

第一条检验正式门槛，目前逐实验返回暂停；第二条显式运行指数价格口径诊断。
缺少完整公司行动的ETF账户即使使用exploratory模式也不能生成绩效，防止将拆分或除息当亏损。
每次先冻结策略参数、代码内容、依赖锁、数据快照和公共源版本，再计算。
`DATA_ROOT/research/运行ID`保存registration、coverage、所有结果、报告、逐日权益和Decimal交易账本。
重放要求同代码字节、配置、依赖锁、快照及模式；公共来源新增版本不会替换原登记输入。
重放逐字段核对完整结果，只有成功后才发布latest。
若源码已改变，应在对应registration记录的提交创建独立工作树并按接手文档配置环境，
再执行重放；不要修改旧registration中的代码哈希以绕过校验。

更换策略规则或修复计算口径时创建新运行，旧运行写失效说明并保留。
不要覆盖最后留出结果后继续选冠军。不要将指数价格诊断称为含分红可投资收益。

## 每日影子运行

```bash
scripts/quant platform daily
scripts/quant platform daily --refresh-public --update-tdx
.venv/bin/python scripts/install_shadow_monitor.py
systemctl --user status quant-longterm-shadow.timer
journalctl --user -u quant-longterm-shadow.service -n 100 --no-pager
```

安装器仅写本用户systemd单元，按UTC 00:30与09:30分别观察美股及A股已结束的交易日，
随机延迟最多120秒；重启后补一次漏跑，不补造历史20日验收。
安装前以隔离的临时XDG_RUNTIME_DIR执行systemd单元解析验证，避免校验工具影响正在运行的用户管理器。
安装成功还需核对timer为active/waiting，并检查首次service的Result和实际生成记录；存在单元文件不代表正在运行。
WSL和用户服务需要运行；Windows关机或WSL停止时不会执行，不能承诺关机也提醒。
没有安装邮件、短信、券商或外部消息发送功能。

输出位于`DATA_ROOT/monitor/latest.json`和`daily/`，包含标的、数据日期、策略版本、
快照、观察值、暂停理由、预算类型、建议额度与失效条件。当前实际账户尚未对账，预算明确为示例。
缺少正式规则/可靠日历/数据/账户时，建议额度与下一可交易时间为null，不伪造买卖动作。

`shadow.json`从实际启动时间起累积每个标的不同的已完成交易日；重复运行不增加天数，
历史回放不能补足20天。满20天仍需结合故障记录验收，系统不会自行晋级为正式建议。

停止定时任务：`systemctl --user disable --now quant-longterm-shadow.timer`。
仅停定时器不影响手动命令和已保存结果。

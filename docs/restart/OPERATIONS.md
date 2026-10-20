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

当前`.venv`关闭system-site-packages，已独立安装206项锁定依赖；不复用其他worktree的editable安装。
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

### 现金池、压力阶段与组合研究

主实验固定源代码为`560877f`，扩展首版为`b448871`，完整账户日历修复版为`ef8eee4`。
首版Put/Call的48条年限标签不能用于五年结论。主研究的六个VIX时间分段边界修正单独保存；
分析时用校验和绑定的修正文件覆盖相应展示行，原运行文件不变。运行ID以任务看板为准。
从原冻结价格研究读取输入，补充源版本在执行前登记，不动态读取“最新”覆盖旧实验。

```bash
scripts/quant platform cash-pool-research /完整路径/原价格研究 --config configs/cash_pool.yaml --workers 4
scripts/quant platform cash-pool-research /完整路径/原价格研究 --config configs/cash_pool.yaml --workers 4 --resume-run /完整路径/中断运行
scripts/quant platform cash-pool-research /完整路径/原价格研究 --config configs/cash_pool.yaml --workers 4 --replay-run /完整路径/完整运行
scripts/quant platform cash-pool-extensions /完整路径/现金池主运行
scripts/quant platform cash-pool-extensions /完整路径/现金池主运行 --replay-run /完整路径/扩展运行
scripts/quant platform analyze-cash-pool /完整路径/现金池主运行 /完整路径/全新分析目录
scripts/quant platform analyze-cash-pool /完整路径/现金池主运行 /完整路径/全新分析目录 --corrections /完整路径/日历修正
scripts/quant platform analyze-cash-pool-extensions /完整路径/扩展运行 /完整路径/全新扩展分析目录
scripts/quant platform fetch-history --first-cftc-year 2006 --last-cftc-year 2026 --first-cffex-month 201004 --last-cffex-month 202609
scripts/quant platform fetch-pressure 2026-10-19
scripts/quant platform issuer-evidence configs/fund_actions/sh512890.json --nav-file /完整路径/已缓存发行人NAV
scripts/quant platform audit-fund-reports /完整路径/现金池主运行 /完整路径/发行人报告目录 /完整路径/全新年报审计目录
scripts/quant platform audit-cftc-releases /完整路径/现金池主运行 /完整路径/全新发布时间审查
scripts/quant platform fetch-shiller
scripts/quant platform refresh-shiller-research /完整路径/现金池主运行 /完整路径/全新估值代理运行 --version 指定版本
scripts/quant platform refresh-shiller-research /完整路径/现金池主运行 /完整路径/全新估值重放 --replay-run /完整路径/估值代理运行
scripts/quant platform audit-price-sources /完整路径/现金池主运行 /完整路径/全新行情来源审查
scripts/quant platform audit-price-sources /完整路径/现金池主运行 /完整路径/全新行情重放 --replay-run /完整路径/行情来源审查
scripts/quant platform current-price-pe-research /完整路径/现金池主运行 /完整路径/全新现价估值实验
scripts/quant platform current-price-pe-research /完整路径/现金池主运行 /完整路径/全新现价估值重放 --replay-run /完整路径/现价估值实验
scripts/quant platform confirmation-horizon-research /完整路径/现金池主运行 /完整路径/全新确认期限实验 --workers 4
scripts/quant platform confirmation-horizon-research /完整路径/现金池主运行 /完整路径/全新确认期限重放 --workers 4 --replay-run /完整路径/确认期限实验
scripts/quant platform verify-research-replay /完整路径/原运行 /完整路径/重放运行
```

重放必须在相应冻结源码工作树执行，可设置`QUANT_PYTHON`指向本项目已核实的解释器，
同时设置`DATA_ROOT`。`scripts/quant`仍使用该工作树自己的源码，不安装到共享editable路径。
初次失败运行只用于保留错误证据；修复后创建新登记，不继续使用原错误代码的声明。
`payloads.json`核对逐日权益、流水、特征、所有案例及事件表的字节哈希，时间戳登记文件不要求相同。
正式交易门槛没有因新增探索命令而放宽。

`verify-research-replay`不仅比较两个清单，还重新读取每个文件计算哈希，并核对登记源码字节。
它不证明金融含义或历史可得性正确；例如旧Put/Call错误窗口可以被精确重复。
`current-price-pe-research`使用独立公式登记，不覆盖整个月度PE滞后的实验；
`confirmation-horizon-research`只延长事件记忆，不改变五日企稳门槛。
两项追加实验均承认已经观察原始历史结果，不将其当成全新样本外验证。

阶段统计和窗口审计脚本使用同一解释器及冻结源码，例如：

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_cash_pool_calendars.py /完整路径/主运行 /完整路径/DATA_ROOT /完整路径/新日历审计.json
PYTHONPATH=src .venv/bin/python scripts/correct_cash_pool_calendars.py /完整路径/主运行 /完整路径/日历审计.json /完整路径/新修正目录
PYTHONPATH=src .venv/bin/python scripts/analyze_stage_funnels.py /完整路径/主运行 /完整路径/估值代理运行 /完整路径/DATA_ROOT /完整路径/新阶段统计目录
PYTHONPATH=src .venv/bin/python scripts/check_valuation_future_invariance.py /完整路径/估值代理或现价估值运行 /完整路径/DATA_ROOT /完整路径/新的因果检查.json
```

冻结工作树没有`.venv`时，将上述解释器路径换成已核验的绝对路径。
日历修正拒绝未登记案例、原记录哈希不符或未通过独立账本的记录；不按收益选择修正。
行情来源审查冻结五个指数和八条规则，要求相同价格日历、资金流及成本；
缺报价时暂停该标的，不能前填价格或缩短账户。两家一致仍不等于官方真实性认证。

### 本轮冻结版本索引

这些是复现入口，不是任务状态。完整路径、输入哈希及重放回执另见研究报告的产物索引。
工作树通过`git worktree add --detach 新目录 提交号`建立，复用经过doctor核验的解释器，
不在共享环境重新安装其他工作树。不要把所有实验都用当前HEAD重新运行后称为原样复现。

| 研究/检查 | 冻结提交 | 命令或脚本 |
|---|---|---|
| 主现金池197项登记 | `560877f` | `platform cash-pool-research` |
| 完整日历的压力、风格、渠道扩展 | `ef8eee4` | `platform cash-pool-extensions` |
| 整个月度PE滞后的Shiller更新组 | `eec3c45` | `platform refresh-shiller-research` |
| 现价除以滞后盈利 | `5f1448d` | `platform current-price-pe-research` |
| 五指数双来源敏感性 | `028fcd3` | `platform audit-price-sources` |
| CFTC整段屏蔽与观察日延迟两种边界 | `b61c76f` | `platform audit-cftc-releases` |
| 20/60/120日确认期限 | `77feca0` | `platform confirmation-horizon-research` |
| 主/扩展分析、六条日历修正、基金年报核验v4 | `b54e45f` | `platform analyze-cash-pool`、`analyze-cash-pool-extensions`、`audit-fund-reports` |
| 确认期限完整配对及原版等价核对 | `70d25c0` | `scripts/analyze_confirmation_horizons.py` |
| 全部十年窗口图 | `eafdf56` | `scripts/plot_cash_pool_windows.py` |
| 三ETF全部月度起点 | `b948f32` | `scripts/research_etf_monthly_windows.py` |
| 月度窗口汇总及最新账户核验 | `cac0b47` | `scripts/analyze_etf_monthly_windows.py` |
| CFTC原假设与主实验的别名声明核对 | `6bdf108` | `scripts/check_release_primary_equivalence.py` |

```bash
PYTHONPATH=src /完整路径/解释器 scripts/analyze_confirmation_horizons.py /完整路径/主运行 /完整路径/确认期限运行 /完整路径/新分析目录
PYTHONPATH=src /完整路径/解释器 scripts/plot_cash_pool_windows.py /完整路径/主分析/adjudicated_results.csv /完整路径/新图表目录
PYTHONPATH=src /完整路径/解释器 /完整路径/check_cash_pool_future_invariance.py /完整路径/确认期限运行 /完整路径/新因果检查.json --registered-confirmations
```

最后一项使用`655f9c0`的验证脚本、`77feca0`的实际研究源码；回执同时记录两者，
不能把检查脚本版本和金融实现版本混为一谈。追加未来行情的检查不是历史发布时间的证明。
年报核验v3曾出现无关源码版本混用，财务文件相同但全源码一致性不通过；
v4在同一冻结版本重算并重放，旧失败回执保留。

月度窗口与性能命令：

```bash
PYTHONPATH=src /完整路径/解释器 scripts/research_etf_monthly_windows.py /完整路径/主运行 /完整路径/新月度运行
PYTHONPATH=src /完整路径/解释器 scripts/research_etf_monthly_windows.py /完整路径/主运行 /完整路径/新月度重放 --replay-run /完整路径/原月度运行
PYTHONPATH=src /完整路径/解释器 scripts/analyze_etf_monthly_windows.py /完整路径/月度运行 /完整路径/主运行 /完整路径/新月度分析
PYTHONPATH=src /完整路径/解释器 scripts/check_release_primary_equivalence.py /完整路径/CFTC边界审查 /完整路径/主运行 /完整路径/新核对.json
```

CPU/GPU优化在独立工作树`/home/yang/projects/quant_performance`，
其源码基线、选择的并行度、GPU适用范围和复现命令只在
[性能审查](/home/yang/projects/quant_performance/docs/restart/PERFORMANCE_AUDIT.md)维护。
`quant_performance_baseline`保留优化前实现；不替换原冻结研究源码，不共享editable安装。
研究解释的唯一正文仍是[CASH_POOL_RESULTS.md](CASH_POOL_RESULTS.md)，
任务状态仍以主项目的`docs/tasks/STATUS.md`为准。

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

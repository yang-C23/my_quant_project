---
name: quant-analyst-myproj
description: "Maintain and research the my_quant_project platform: trusted market data, cash-pool broad-index and dividend-low-volatility studies, reproducible reports, and CPU/GPU execution under a shared resource budget. Use for work on this repository or this WSL2 quant platform, not unrelated finance questions."
---

# 量化平台研究与维护

本skill的权威版本在仓库skills/quant-analyst-myproj。对当前checkout工作，不切换共享editable安装。
本机主项目为/home/yang/projects/my_quant_project；从其它工作树接手时先确认实际路径。
下文文件路径均相对当前仓库根目录，不相对本机skill安装目录。

## 接手与事实来源

1. 阅读当前仓库的AGENTS.md和docs/ONBOARDING.md。
   任务进度只维护docs/tasks/STATUS.md；在途及旧冻结工作树保留。
2. 检查git status、当前分支、工作树及scripts/quant doctor。
   主环境使用项目.venv或明确的QUANT_PYTHON，入口固定实际源码位置。
3. 先读docs/restart/CASH_POOL_RESULTS.md，再决定是否需要新计算。
   已完成的大批次不因接手或算力空闲而重复启动；新增假设独立登记。
4. 数据和研究分别遵循docs/data_platform.md、docs/restart/RESEARCH_PROTOCOL.md及当前实验登记。
   Parquet/原始证据是长期存档；Qlib是可重建适配层。数据库旧命令仅用于明确的历史复现任务。

## 每次重计算的默认条件

执行前读取docs/COMPUTE_POLICY.md和configs/compute_defaults.json，运行：

```bash
scripts/quant resources --workload account_batch
```

实测主机为12物理核/24逻辑CPU、约47GiB内存及RTX 5090；每次以实际亲和性、配额和总占用为准。
已验证的独立账户批处理空闲上限12worker，按标的研究4，TDX更新4，来源核查3，I/O为2。
其它研究忙时新增上限6，并受余下CPU/内存限制。内部BLAS/OpenMP/Arrow线程默认1。
单账户保持时间顺序，跨标的/策略/窗口才适合多进程；复用数据和特征，避免传输大型对象。

配置列出的scripts/quant platform重任务会自动检查资源和跨工作树准入锁。
直接脚本使用scripts/quant compute-run --workload 对应类别 -- 完整命令，
显式传递--workers '{workers}'，或读取包装器提供的QUANT_WORKERS。
锁忙或资源不足返回75，先完成其它轻量工作，之后重试，不停止原研究、不各自扩张worker。
资源记录在DATA_ROOT/audits/compute。新任务内存估计不可靠时先测小批，不能直接套12worker。

默认账户与日更使用CPU。GPU只在可批量、重复调用且包括冷启动/传输/同步/取回后有净收益时使用。
GPU隔离环境及实测命令见docs/restart/PERFORMANCE_AUDIT.md；不为了利用率扩大参数搜索。
金额、费用、分红和资金守恒保留Decimal；信号、成交日、方向和逐笔账本精确一致，
并检查追加未来数据不改变过去记录。浮点容差在实验前固定，不为通过核验放宽。

## 研究及阶段交付

本阶段以宽基和红利低波、每月积累现金、信号后分批买卖为主，普通定投是对照。
只使用当时可得的信息，成交规则按已登记版本；价格指数、全收益和真实ETF分开报告。
保留全部参数、负结果、未入场、暂停及修正依据。已见历史不能重新称作未见样本外。
资金到账才能支出；入金不是利润；应收分红和可用现金区分，不能重复计分红/费用。
历史数据或许可未通过时继续输出暂停，不把期权成交/OI代理当爆仓或真实净Gamma事实。

是否收尾按docs/restart/PHASE_CLOSEOUT.md的证据条件决定，不因算完或时间到就封版。
用户当前优先问题是标普500/纳斯达克100的长期持有与入场、退出取舍；不能先假设不需止盈。
更新唯一状态源，记录代码/配置/快照及复现命令。
提交前跑相关测试、lint和真实回归；大数据与秘密留在仓库外，完整结果通过清单和哈希索引。
遵循用户当前的发布授权；本skill不自行授权推送、合并主分支、购买、交易或外部通知。
仓库版本和本机已安装skill保持同步；不要恢复旧模型专属角色、旧数据库密码示例或自动推送规则。

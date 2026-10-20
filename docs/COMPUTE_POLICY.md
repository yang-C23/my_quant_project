# 默认计算资源与执行条件

机器可读默认值只有一份：[compute_defaults.json](../configs/compute_defaults.json)。
实测证据见[性能审查](restart/PERFORMANCE_AUDIT.md)。它们是执行设置，不是金融策略参数。

2026-10-20实测：Ryzen 9 9900X，12物理核/24逻辑CPU，WSL约47.04GiB内存；
RTX 5090约32,607MiB显存。亲和性、cgroup配额、可用内存和其它任务负载每次重新读取，
不能将这份硬件清单当成任何工作树都可独占的资源承诺。

## 默认值与适用范围

| 工作负载 | 空闲时默认上限 | 使用条件 |
|---|---:|---|
| 独立账户批处理 account_batch | 12进程 | 52账户梯度实测；16进程更慢；每worker先预算0.5GiB |
| 按标的完整研究 asset_study | 4进程 | 完整研究已核验；不把账户任务的12进程最优值套给不同调度器 |
| 五指数来源核查 source_audit | 3进程 | 保留已验收的配置，未声称是性能最优 |
| 通达信更新 tdx | 4进程 | 保留更新验收配置，先预算3GiB/worker；本轮未重测全市场ETL梯度 |
| 数据源I/O io | 2并发 | 同时遵守发布者访问频率；算力多不提高抓取限额 |
| 顺序计算 serial | 1进程 | 单账户内部日期顺序不并行 |
| 可选GPU历史批量 gpu_history | 1控制进程 | 仅显式调用、反复计算且总耗时有净收益时使用 |

内存预算包含保留4GiB系统余量和0.5GiB控制进程余量；这些是保守调度估计，
不是每种未知任务的内存上限证明。新工作负载先小批测峰值，再调整自身配置。
CPU至少保留2个逻辑核；小配额主机相应缩减保留量，资源不足时返回defer，不强行启动1个worker。
其它研究实际占用达到1核时，新增任务最多6worker，并继续受总CPU/内存剩余量约束。
原生BLAS/OpenMP/MKL/NumExpr/Arrow线程数默认1；采用多进程并行独立账户，单账户保持串行。

## 日常入口

```bash
scripts/quant doctor
scripts/quant resources --workload account_batch
scripts/quant platform cash-pool-research /绝对路径/已冻结输入
```

最后一条以及配置列出的重型platform命令自动获取同用户、跨工作树的准入锁，
重新采样资源，并在未指定workers时注入本次预算。显式workers超过本次预算会拒绝启动。
另一个受管理的重任务运行时返回退出码75，保留原任务，稍后重试；不终止进程。
使用锁是为了让多个agent不能各自申请12worker。未使用此入口的旧任务仍通过总负载采样计入。
样本负载不能保证预测其它非受管理程序下一秒的峰值，长任务仍需监测。

直接脚本使用统一包装器，`{workers}`必须作为独立参数或`--workers={workers}`传入：

```bash
scripts/quant compute-run --workload account_batch -- \
  /绝对路径/项目Python scripts/benchmark_quant_workers.py \
  /绝对路径/原研究 /绝对路径/全新输出 \
  --workers '{workers}' --scheduling case --config configs/performance_audit.yaml
```

包装器提供`QUANT_WORKERS`、内部线程限制及资源回执；脚本必须实际使用worker参数或该变量。
不要嵌套compute-run或在其中再次调用自动准入的scripts/quant platform重任务。
旧CLI、库直接调用和未包装脚本保持兼容，但没有自动资源准入；启动者负责用包装器。
`--help`、doctor、lint和小型离线测试不占重任务锁。
每次执行在`DATA_ROOT/audits/compute/`追加plan/result JSON，保存预算、配额、聚合占用、
配置SHA256、完整命令的哈希、退出码及耗时；不记录可能包含凭据的原始进程参数。

## GPU条件与金融精度

默认GPU后端为CPU。真实历史百分位CPU约51ms，GPU热调用约1.67ms，
首次调用含编译约382ms；每日3个新观测CPU约0.9ms。
因此日常小增量、现金账本和顺序状态机继续CPU；GPU不得因为空闲就强制启用。
GPU隔离环境与锁见性能报告，主环境不自动安装CUDA库；首次调用前检查兼容性和已有显存占用。

金融现金、费用、分红到账和资金守恒保留Decimal；优化要求信号、日期、方向和逐笔账本一致。
历史中位秩使用float64及相同并列值规则，决策边界不得以“收益接近”验收。
预热、传输、同步、结果取回和冷启动分别计时；全部结果和失败保存。
改变环境、数据规模或调度器后，重新测小型真实工作负载；不重启全部已完成的金融参数搜索。

冻结研究仍在其原提交和原工作树重放，不把本入口的新资源策略或当前HEAD冒充旧代码。

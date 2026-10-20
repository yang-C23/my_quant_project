# 2026-10-20 CPU/GPU实际性能审查

本次优化在独立分支 `task/TASK-080-cpu-gpu-throughput`、
`/home/yang/projects/quant_performance` 实施。原研究、数据和运行进程均保留。
冻结优化前代码为 `74614ce`，金融计算优化为 `d6dba5c`；
同步GPU分段计时为 `6ffa9b9`，全研究等价核验为 `af67f42`。
研究范围和假设没有增加，所有优化实验包括失败日志均保留。

后续整合说明：用户要求将已验收优化作为日常默认使用条件。
本报告及同一性能实现现已整合至主项目任务分支；原性能工作树和原回执保持不变。
新任务的动态预算和准入规则见[默认计算条件](../COMPUTE_POLICY.md)，
该规则本身不改变下文历史基准测试的计时或登记。新增默认入口的回归另存，不能替换原性能证据。

## 实际资源与约束

- WSL2内核 `6.6.87.2-microsoft-standard-WSL2`；
  Ryzen 9 9900X，12物理核/24逻辑CPU，亲和性0—23。
  cgroup CPU/memory没有额外硬配额；约47.04GiB内存、12GiB未用交换空间。
- RTX 5090，32,607MiB显存，Windows驱动610.88。
  初查GPU使用约87MiB、利用率0%，没有其他CUDA研究。
  计算能力12.0与[NVIDIA官方表](https://developer.nvidia.com/cuda/gpus)一致。
- 初查全部研究进程合计约4.94个CPU核、6.02GiB累计RSS，
  不是每个任务都能独占24核。RSS含共享页，后续同时报告USS。
  多个已完成工作的worker仍驻留，但没有因为空闲而终止它们。
- 原研究使用Python3.10，系统CUDA编译器12.5。
  单独创建 `/home/yang/venvs/quant_gpu_benchmark`：
  Python3.13.5、CuPy14.2.0、CUDA组件wheel及NVRTC13.4，
  NumPy2.2.6/Pandas2.3.3/Arrow19.0.1与CPU对照保持相同。
  5090实际执行双精度及自定义核函数成功；未替换系统CUDA或主研究环境。
  可选环境锁为 `requirements-gpu-benchmark-lock.txt`；
  使用组件wheel的方法见[CuPy安装说明](https://docs.cupy.dev/en/stable/install.html)。
  文档列出的工具链版本与本机实际组合分开记录，不以安装成功代替计算验证。

资源原始记录位于
`/home/yang/quant_data/audits/performance-20261020/resources-before-benchmarks.json`。
基准测试之间串行进行；BLAS/OpenMP/MKL/NumExpr限制为1，
worker中的Arrow CPU/IO池也设置为1。线程总数包含已创建但空闲的库线程，
判断过度订阅以实际CPU时间而非线程数量为依据。

## 先测量，再改变

对纳斯达克100、沪深300、510300和512890的完整历史，各跑0/50%底仓，
共8个真实账户。输入版本和规则不变，cProfile记录如下，单位秒：

| 环节 | 优化前 | 优化后 |
|---|---:|---:|
| 读取价格 | 0.0165 | 0.0162 |
| 读取公司行动 | 0.0036 | 0.0034 |
| 校验输入、公司行动和因果总回报准备 | 2.9351 | 0.0312 |
| 滚动统计单独测量¹ | 0.0045 | 0.0044 |
| 完整阶段信号，含滚动统计/KDJ | 0.5980 | 0.0918 |
| 账户执行，含Decimal及绩效 | 4.8797 | 4.7958 |
| 独立账本核验 | 101.2788 | 0.7382 |
| 写出账户文件 | 0.2233 | 0.2256 |
| VIX五年历史百分位，单独完整历史任务 | 2.8824 | 0.0245 |
| 全部仪器化任务墙钟 | 112.9507 | 6.0599 |

¹滚动统计是独立小任务，不能再加到完整阶段耗时中解释阶段占比。
这里的清洗是冻结研究输入及公司行动准备，不代表重新跑完整2,975万行TDX ETL。
cProfile改变程序开销，因此最终加速比使用后文未开启cProfile的端到端基准。

Decimal账本入口的调用次数完全相同：deposit 2,904、buy 4,482、
settle/equity各119,238、dividend 39、split 3。
这些入口累计包含时间约0.36秒，远低于原来重复DataFrame筛选的开销。
这不是对所有Decimal运算指令的单独计时，账户unitization等运算仍在账户总时间内。
8账户剖析没有出售，出售行为由52账户和全部研究核验覆盖。
`ledger.py`、交易引擎、现金池执行和绩效公式没有被修改。

实际改动：

1. 独立审查先把稀疏流水索引成按日期排列的记录，再逐日以相同Decimal运算顺序重建。
   不再每天反复创建空DataFrame、筛选和转换记录；独立审查仍不调用交易账本。
2. 公司行动的顺序递推保持原运算顺序，只把逐单元格Pandas读写换成数组访问和最终整列写回。
3. 阶段计算直接调用原KDJ递推，避免为提取J值而先跑一遍无关的旧恐慌状态机。
4. 百分位使用日历窗口边界、有效样本计数和整数并列计数，保留历史严格早于当前日及半权重并列规则。
5. 独立账户任务仅传标的/策略/窗口ID；每个worker缓存输入和特征，
   单账户内仍严格按时间顺序执行。配置控制的52账户调度器按账户分配，
   完整主研究核验则仍使用原按标的的调度，分别记录两者的适用范围。

## 同一真实工作负载的CPU端到端对照

冻结选择：纳斯达克100、沪深300、510300、512890、515100；
无条件、企稳、50%底仓企稳、企稳后退出四规则；
全部历史/最近五年/最近十年中真实支持的窗口，共52账户。
选择原因是历史长度、OHLC、分红和拆分覆盖，不是收益排名。
包括进程启动、输入读取/准备、账户计算、独立审查、文件写出、逐文件SHA256比对。
每次均检查五个金融文件/账户，并逐值核验阶段特征。

| 实现/任务分配 | workers | 墙钟中位数秒 | 账户/秒 | 平均占用CPU核 | 峰值累计RSS MiB | 峰值USS MiB |
|---|---:|---:|---:|---:|---:|---:|
| 原版/按标的 | 1 | 156.124 | 0.333 | 1.03 | 413.6 | 229.3 |
| 原版/按标的 | 4 | 56.239 | 0.925 | 2.89 | 1000.4 | 529.4 |
| 优化/按账户 | 1 | 8.857 | 5.871 | 0.93 | 414.0 | 242.1 |
| 优化/按账户 | 2 | 4.928 | 10.553 | 1.82 | 644.9 | 366.2 |
| 优化/按账户 | 4 | 2.968 | 17.519 | 3.62 | 1073.9 | 605.3 |
| 优化/按账户 | 6 | 2.337 | 22.253 | 5.27 | 1478.7 | 815.3 |
| 优化/按账户 | 8 | 2.005 | 25.940 | 6.84 | 1892.0 | 1036.5 |
| 优化/按账户 | 12 | 1.882 | 27.637 | 9.60 | 2698.8 | 1464.1 |
| 优化/按账户 | 16 | 2.088 | 24.908 | 11.38 | 3482.3 | 1859.0 |

除原单进程测一次外，每个配置测三次，共25轮、1,300次账户重放。
同为4进程时约18.95倍；采用12进程相对原4进程约29.89倍。
原1进程到优化1进程约17.63倍，主要收益来自删除重复工作。
12进程三次为1.863/1.882/2.035秒；16进程为2.054/2.088/2.162秒，
增加逻辑线程数已经降低吞吐。按照“中位耗时距最快不超过5%时选择较少进程”，采用12。
1—6进程阶段保留旧任务预算，8/12/16在旧任务自然完成后执行，未终止研究。
这项选择适用于已测的按账户批处理；完整主研究的按标的核验使用4进程，
其长历史长尾仍存在，不把两个调度方式的worker数混为一个平台通用最优值。
有其它重计算任务时先重新汇总资源，保守采用不超过6个新增worker；
空闲时仍至少保留2个逻辑CPU，并按新增任务实际内存调整。

表内工作负载计时包含worker启动至结果写出和哈希核验；
主解释器导入、登记文件写入在这个计时区间之前，另做完整CLI外部计时，避免隐藏启动成本。
全部原始试次、最小/最大值和选择依据在`summary/`，不只保留最好的那次。

完整CLI复测同样52账户：原4进程56.6177秒，优化12进程2.48646秒，
包含主解释器启动、导入、登记及全部处理，**完整命令加速22.77倍**。
对应吞吐约0.918和20.913账户/秒，两次均260个金融文件精确相同。
采样峰值RSS约998.1/2704.7MiB、USS约529.1/1471.4MiB；
此账户任务GPU利用率0%，设备已用87MiB。与GPU特征实验的显存数字分开报告。
原始记录为`cli-baseline-w4-resources/`和`cli-optimized-w12-resources/`。
含这两轮共1,404次账户重放通过；性能重复次数不增加投资证据的独立样本量。

![CPU吞吐与GPU冷/热成本](/home/yang/quant_data/audits/performance-20261020/summary/throughput.png)

输入已在操作系统页缓存中。优化1—6进程期间系统物理读盘记录为0，
系统写盘约16MiB/批；这是系统计数，含其它任务，不能误称本进程独占磁盘吞吐。
原4进程均匀分不到四个核心，原因是各标的长度不同，最后只剩长历史worker。
内存不是这组工作负载的限制；不能由52账户的峰值推断任何大型研究都能安全开相同worker数。

## GPU真正加速了什么

真实工作负载为Cboe VIX/VXN/SKEW共22,851个日观测的五年历史中位秩，
没有复制数据扩充规模。CPU/GPU都使用隔离环境的Python3.13.5和相同输入，
与上述Python3.10账户基准分开比较。
该子任务从已载入内存的真实Series开始；共同的catalog读盘和下载不计入两端，
主机/设备之间的传输则完整计入。因此它不是原始数据下载到投资报告的整平台加速比。

第二次完整运行同时采样资源：

| 实现 | 端到端耗时 |
|---|---:|
| 原CPU历史实现 | 2.8323秒 |
| 优化CPU，五次中位数 | 0.05126秒 |
| GPU首次：导入、context、编译、传输、计算、同步、取回 | 0.38178秒 |
| GPU热调用，五次中位数 | 0.001668秒 |
| CPU只更新三个最新观测，五次中位数 | 0.000900秒 |

热调用相对优化CPU约30.72倍；首次GPU调用反而慢于优化CPU约7.45倍。
另一轮完整运行分别得到CPU约50.10ms、GPU热调用约1.72ms、首次327.74ms；
结果未只挑最快的一次。
GPU全过程计入主机准备、约388,467字节H2D、同步内核、182,808字节D2H及Series构造。
单轮分段典型耗时：主机约1.1ms、H2D约0.15ms、内核/分配/同步约0.27ms、
D2H约0.08ms。没有把异步提交时间当执行时间；
原因见[CuPy性能测量说明](https://docs.cupy.dev/en/stable/user_guide/performance.html)。

资源采样峰值：主机RSS约592.5MiB、USS约584.7MiB，
整张GPU已用显存584MiB，包含context和桌面；CuPy数据池约0.55MiB。
100ms加SMI调用开销的采样中GPU利用率峰值4%，会漏掉不足1ms的短核函数，
不能把它当SM瞬时峰值或强求达到100%。

最终执行原则：Decimal账户、顺序状态机和每日少量更新继续CPU；
可选GPU后端用于同一进程内多次批量重建历史百分位。
它不会自动改写金融规则，也不会因为GPU可用就默认启用。
当前完整研究的主要工作是账户和独立核验，百分位可缓存且只需少量重建，
因此不将30倍局部热调用收益冒称整个回测的GPU加速比。

## 精度与证据

事先固定的精度要求在 `configs/performance_audit.yaml`：
现金/成交/逐笔流水、信号和日期必须一致；历史中位秩float64精确一致；
仅非决策诊断允许事先规定的rtol/atol各1e−12，不用容差掩盖阈值翻转。
GPU关闭FMA，使用精确除法；没有改为float32。

- 剖析8账户的40个文件逐字节相同。
- 每次52账户基准的260个文件逐字节相同，阶段特征逐值精确一致。
- GPU实际全历史、16组并列/缺失/非正值/无穷/日历预热/扩展窗口边界测试，
  以及0.1/0.3/0.4/0.7/0.8/0.9/0.95阈值判断全部精确相同。
- GPU追加未来数据不改变过去百分位。
- 15项已登记确认期限规则×12资产，共180次真实数据未来追加测试：
  公司行动处理、特征、过去每日账户和过去逐笔流水完全相同。
- 优化分支319项离线测试通过，3项遗留集成测试未运行；2项上游Pydantic弃用警告保留。
- 全部14,205主研究账户已重新计算，耗时1,248.62秒；
  85,359个文件中85,326个与原主运行逐字节一致。
  首次直接比较得到33个差异，原负结果
  `full-study-equivalence/performance_equivalence.json`保留。
  差异源于优化之前已有的6个VIX日历裁定及其汇总，
  另6份来源说明增加了`conservative_publication_bounds: null`。
  以事先保存的日历裁定为基准，逐笔和逐日文件精确相同，记录/汇总值精确相同，
  没有容差放宽；见`full-study-adjudicated-equivalence.json`。
  原始`560877f`和性能基线`74614ce`之间这些既有改动，不能归因于本次性能优化。
  不把这次不同源码的等价核验冒称同源码重放，也不把全量历史运行时间当受控加速比。
  又以`74614ce`优化前实现单独重算这6个已裁定账户，30个金融文件全部逐字节一致；
  证据在`six-calendar-baseline/summary.json`，复现配置为
  `configs/performance_calendar_cases.yaml`，源输入选择上述`full-study-equivalence`目录。

首次两次GPU脚本启动因隔离环境缺PyYAML/Backtrader失败，
未产生金融结果；安装缺失依赖后两次实际完整GPU实验成功。
早期一次pytest命令误用了不存在的测试文件，未运行测试；随后正确执行相关测试和全部离线测试。
这些命令日志保留，不计入成功检查数。

## 复现入口

所有产物位于 `/home/yang/quant_data/audits/performance-20261020`，
程序拒绝覆盖已有目录。重跑请给出新输出路径。
交付清单为[delivery.json](/home/yang/quant_data/audits/performance-20261020/delivery.json)，
关联运行、核验回执、报告和日志的SHA256。`logs/`保留成功与失败的命令输出；
最终范围检查曾漏登记可选GPU依赖锁，任务卡补齐后重新通过，原失败日志仍保留。
`resources-after-benchmarks.json`采样时仍在运行最终离线测试，不能当作完全空闲基线。

```bash
cd /home/yang/projects/quant_performance
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONPATH=src

/home/yang/projects/my_quant_project/.venv/bin/python \
  scripts/benchmark_quant_workers.py \
  /home/yang/quant_data/research/cash-pool-20261020T180251782214Z \
  /home/yang/quant_data/audits/new-cpu-benchmark \
  --workers 12 --scheduling case --config configs/performance_audit.yaml

/home/yang/venvs/quant_gpu_benchmark/bin/python \
  scripts/benchmark_quant_gpu.py /home/yang/quant_data \
  /home/yang/projects/quant_performance_baseline \
  /home/yang/quant_data/audits/new-gpu-benchmark

/home/yang/projects/my_quant_project/.venv/bin/python \
  scripts/verify_optimized_study.py \
  /home/yang/quant_data/research/cash-pool-20261020T180251782214Z \
  /home/yang/quant_data /home/yang/quant_data/audits/new-full-equivalence --workers 4 \
  --corrections /home/yang/quant_data/audits/cash-pool-session-20261020/calendar-corrections
```

原版CPU对照使用同一benchmark脚本，但cwd/PYTHONPATH改为
`/home/yang/projects/quant_performance_baseline`，`--scheduling asset`。
`registration.json`同时记录被测源码、基准脚本哈希、配置及输入哈希。
完整CLI计时可用`measure_quant_command.py 新资源输出目录 -- 完整Python命令`包装以上命令。
三次梯度汇总命令为
`scripts/summarize_quant_performance.py 原始基准目录 新汇总目录`；
选择规则保存在`configs/performance_selection.yaml`，它只选择执行并行度，不选择投资策略。
工作树继续有变动时，应从记录的Git版本建立新只读工作树再复现，
不把当前HEAD视为以前运行时的源码。

剩余瓶颈是长历史账户的顺序计算、核心/择时双账户合并、完整研究按标的分配后的长尾，
以及大批小文件写出。金额精度和已登记实验不为提高利用率而牺牲。

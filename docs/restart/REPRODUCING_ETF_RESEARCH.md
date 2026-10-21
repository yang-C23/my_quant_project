# 本轮ETF研究的复现与交接

2026-10-21。先看[晨间审阅](MORNING_REVIEW_20261021.md)及[完整结果](ETF_TOTAL_RETURN_RESULTS.md)。
所有运行已完成并重放，不要默认重新启动。数据在仓库外，Git只保存代码、配置和摘要。
最终任务状态只看[STATUS.md](../tasks/STATUS.md)。

## 冻结版本映射

`DATA_ROOT=/home/yang/quant_data`（实际程序从Settings/.env读）；基础快照仍为`20261020T112255Z-2f1a3256f7`。

| 研究目录名（位于DATA_ROOT/research） | 配置 | 代码 | 去重账户 | 配对产物数 |
|---|---|---|---:|---:|
| etf-total-return-v2-20261021 | etf_total_return_v1.json | 2ba339d | 3,697 | 22,245 |
| etf-source-sensitivity-v1-20261021 | etf_source_sensitivity_v1.json | 2ba339d | 2,898 | 17,453 |
| etf-fixed-principal-v1-20261021 | etf_fixed_principal_v1.json | 2ba339d | 2,488 | 14,993 |
| etf-tax10-v1-20261021 | etf_tax10_v1.json | 2ba339d | 330 | 2,045 |
| cash-wait-bil-v1-20261021 | cash_wait_bil_v1.json | 2ba339d | 143 | 1,050 |
| cash-wait-bil-source-v1-20261021 | cash_wait_bil_sensitivity_v1.json | 2ba339d | 143 | 1,050 |
| etf-event-order-v1-20261021 | etf_event_order_v1.json | d49441e | 136 | 881 |

每个目录均有同名`-replay`，总9,835账户、59,717对产物精确相同。
独立实现核验全部现金账本；另外实际读取119,434文件重新计算SHA256，
证据在`audits/us-etf-20261021/full-rehash/acceptance.json`和`actual_file_hashes.csv`。
不是只比较两个旧清单相等。

冻结工作树：

- `/home/yang/projects/quant_etf_frozen_v2` → `2ba339d3e2bf74ba6afb007176756722062410a7`。
- `/home/yang/projects/quant_etf_event_order_frozen` → `d49441ec23c97834ba0f8678f9aa21fb26dfa8c9`。
- `/home/yang/projects/quant_etf_frozen_b6536b0`保留首轮输入拒收现场。
- 旧价格研究工作树`quant_entry_horizons_frozen_d76a043`保持原样；其NDX缺价勘误不原地覆盖。

各工作树通过`scripts/quant doctor`固定实际源码，不能依赖共享环境里的editable安装位置。
最终文档提交不替代各研究自己的源码身份。`registration.json`包含完整提交、源码/配置摘要和运行协议。

## 必须保留的证据

每个研究目录保留`inputs/`、`registration.json`、`payloads.json`、`jobs.json`、
账户的`daily.parquet`、`journal.parquet`、`metrics.json`、`ledger_audit.json`和未来追加核验。
主组`eligibility_exclusions.json`保存76个估值起点排除；`cohorts.json`及`all_cohort_results.csv`
保留满期、未满期、未入场，不能只复制获利账户。

原始来源在`source_probes/us-etf-20261021`、`source_probes/sp500-long-20261021`。
日历在`audits/entry-horizons-20261021/xnys-sessions.json`，实际收盘在
`audits/us-etf-20261021/xnys-closes.json`。捕获摘要新增裁定在`archive-integrity-v1`，
说明早期一份拒收为何没有改变任何金融信号，见[数据审查](ETF_DATA_AUDIT.md)。

保留失败：`etf-total-return-v1-20261021`因截断估值文件在账户计算前失败；
`source-audit-v1/v2`分别暴露非数值/错误支付日；v3为完成版。
先导24账户、网络失败回执、旧报告v1/v2以及补充诊断v1/v2/v3都保留。
这些不得与成功的完整研究相加，不能删除后只展示成功运行。

## 重放命令

先使用对应冻结工作树。下例重建到**新的、不存在的目录**，不覆盖现有`-replay`。
共同CPU预算自动决定worker；账户批处理空闲实测上限12，内部BLAS/OpenMP/Arrow线程1。
若返回75，等待其他研究完成，不能另开树绕过共享锁。

```bash
cd /home/yang/projects/quant_etf_frozen_v2
scripts/quant doctor
scripts/quant resources --workload account_batch
scripts/quant compute-run --workload account_batch -- .venv/bin/python scripts/run_entry_horizons.py \
  /home/yang/quant_data/research/etf-total-return-v2-review-replay \
  --config configs/etf_total_return_v1.json --workers '{workers}' \
  --replay /home/yang/quant_data/research/etf-total-return-v2-20261021
```

来源/无月供/税率实验使用表中配置和对应原始目录，命令入口相同。
原始输入从旧产物重放，不重新联网拉取今天已经修订的资料。

```bash
scripts/quant compute-run --workload account_batch -- .venv/bin/python scripts/run_cash_wait.py \
  /home/yang/quant_data/research/cash-wait-bil-v1-review-replay \
  --config configs/cash_wait_bil_v1.json --workers '{workers}' \
  --replay /home/yang/quant_data/research/cash-wait-bil-v1-20261021

cd /home/yang/projects/quant_etf_event_order_frozen
scripts/quant compute-run --workload account_batch -- .venv/bin/python scripts/run_entry_horizons.py \
  /home/yang/quant_data/research/etf-event-order-v1-review-replay \
  --config configs/etf_event_order_v1.json --workers '{workers}' \
  --replay /home/yang/quant_data/research/etf-event-order-v1-20261021
```

实际全量重算产物核验命令在最终任务工作树执行，验证器查找每个原目录对应的`-replay`：

```bash
cd /home/yang/projects/my_quant_project
scripts/quant compute-run --workload io -- .venv/bin/python scripts/verify_research_payloads.py \
  /home/yang/quant_data/audits/us-etf-20261021/full-rehash-review \
  --workers '{workers}' \
  --run /home/yang/quant_data/research/etf-total-return-v2-20261021 \
  --run /home/yang/quant_data/research/etf-source-sensitivity-v1-20261021 \
  --run /home/yang/quant_data/research/etf-fixed-principal-v1-20261021 \
  --run /home/yang/quant_data/research/etf-tax10-v1-20261021 \
  --run /home/yang/quant_data/research/cash-wait-bil-v1-20261021 \
  --run /home/yang/quant_data/research/cash-wait-bil-source-v1-20261021 \
  --run /home/yang/quant_data/research/etf-event-order-v1-20261021
```

## 统计、图表和完整配对

权威统计输出`audits/us-etf-20261021/report-v2`：

| 文件 | 用途 |
|---|---|
| all_summaries.csv | 全部规则/期限/退出/底仓，含覆盖、年化、XIRR、回撤、现金、分红、本金亏损 |
| entry_paired_rows.csv / entry_paired_effects.csv | 同原点同终点，等待入场与直接分批的逐行/汇总差值 |
| exit_paired_rows.csv / exit_paired_effects.csv | 同规则入场后的退出、底仓逐行/汇总效果 |
| all_worst_cases.csv | 亏损与最差账户路径索引，不只保留中位数 |
| era_summaries.csv / price_only_era_diagnostic.csv | 新ETF年代分层与旧价格诊断分开 |
| valuation_coverage.csv | 历史估值有效日期，不能隐藏断档 |
| cash_wait_summaries.csv | 零息/BIL/直接投入的等待成本，区分仍等待、删失和排除 |
| 各诊断_all_pairs.csv | 来源、月供0、税率和事件规则的全部配对；不同资金计划不解释为策略超额 |
| spy_10y.png / qqq_10y.png | 不同队列的描述图，不是配对收益优势图 |

该目录及同名`-replay`、补充诊断`diagnostics-v4`及其重放，总30对报告产物实际重新计算摘要完全一致。
机器证据`report-reproducibility-final.json`。图表PNG/SVG已目视检查。

```bash
cd /home/yang/projects/quant_etf_frozen_v2
scripts/quant compute-run --workload io -- .venv/bin/python scripts/report_etf_total_return.py \
  /home/yang/quant_data/research/etf-total-return-v2-20261021 \
  /home/yang/quant_data/audits/us-etf-20261021/report-review \
  --cash /home/yang/quant_data/research/cash-wait-bil-v1-20261021 \
  --diagnostic /home/yang/quant_data/research/etf-source-sensitivity-v1-20261021 \
  --diagnostic /home/yang/quant_data/research/etf-fixed-principal-v1-20261021 \
  --diagnostic /home/yang/quant_data/research/etf-tax10-v1-20261021 \
  --diagnostic /home/yang/quant_data/research/etf-event-order-v1-20261021 \
  --old-price /home/yang/quant_data/research/entry-horizons-v2-20261021

cd /home/yang/projects/my_quant_project
scripts/quant compute-run --workload io -- .venv/bin/python scripts/report_etf_diagnostics.py \
  /home/yang/quant_data/research/etf-total-return-v2-20261021 \
  /home/yang/quant_data/research/etf-event-order-v1-20261021 \
  /home/yang/quant_data/research/cash-wait-bil-v1-20261021 \
  /home/yang/quant_data/research/cash-wait-bil-source-v1-20261021 \
  /home/yang/quant_data/audits/us-etf-20261021/diagnostics-review
```

追加事件规则与主规则**不是全文件相同**：408个金融相关文件中60个daily文件的trigger列不同。
现金、持仓、收益精确相同；136份journal与136份metrics逐字节相同。
只有同一代码、同一规则的重放才要求所有登记产物相同。不能混淆跨策略对比与复现检查。

## 工程与运行边界

355项离线测试通过，3项旧集成测试未运行，2项上游Pydantic弃用警告保留；
lint、doctor及提交范围检查以本轮验收回执为准。
主批性能实测在`main-v2-performance`，包括整个命令时间、进程CPU/内存及GPU采样；
本次不重跑已验证的旧CPU/GPU性能基准，不用不同任务规模制造加速比。
默认资源配置、所有入口及工作skill已在本轮之前整合，见`docs/COMPUTE_POLICY.md`。

本轮仍是探索研究。正式策略晋级、真实税率/渠道、永久保存和再分发许可、20个未来交易日都没有被测试通过替代。
Git交付不带`.env`、凭据、原始行情、全部账本或供应商文件。用户未授权上传，保留本地提交与备份。

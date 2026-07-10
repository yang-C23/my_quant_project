# STATUS.md — 任务看板（唯一状态源）

> 公告：当前开发环境 = `my_quant_env`（若 TASK-001 触发新建 `my_quant_v2`，由其 review 更新本行）。
> 状态机与流程见 `docs/workflow.md`；`backlog` 的卡不许认领。
> **冷接手**：先读 `docs/ONBOARDING.md` 按角色分流。开发者只做**状态=ready 且指派给你（或无指派）**的一张卡；改动文件不得超出该卡 `## Files to touch` 白名单（由 CI `scripts/check_whitelist.py` 强制）；提交前须跑通卡内全部验收命令 + 质量门（`ruff`、`pytest -m "not integration"`）。

| ID | 标题 | 里程碑 | 状态 | 分支 | 依赖 | 备注 |
|---|---|---|---|---|---|---|
| TASK-001 | src 布局迁移 + pyproject | M0 | done | merged 2badc79 | — | env=`my_quant_env`（qlib 0.9.7 兼容，无需新env）；review PASS |
| TASK-002 | GitHub Actions CI | M0 | done | merged 202a059 | 001 | review PASS（云端绿灯待用户确认） |
| TASK-003 | config 设置模块 | M0 | done | merged b9a2327 | 001 | review PASS |
| TASK-004 | 死代码清理 | M0 | done | merged b2987c4 | 001 | review PASS；**M0 gate 通过**（M0-gate-report.md） |
| TASK-010 | 镜像+并行解析→staging | M1 | done | merged | 003 | review PASS；zip 基线范围修订见卡面；28.67M 行/41s |
| TASK-011 | 元数据/标志位 staging | M1 | done | merged | 010 | 返工后 PASS；securities: main 3472/gem 1433/star 608/bse 560/b 165/bond 970/etf 2576/index 2127/other 258 |
| TASK-012 | 向量化复权因子 | M1 | done | merged | 011 | review PASS；hfq 与 PG 5 复杂样本全历史**逐位相等**；全市场 derive 1m51s |
| TASK-013 | qlib dump | M1 | done | merged | 012 | review PASS；全量 29.34M 行/2m18s；D.features vs PG 5.8e-8（f32 界内）；**016 口径：对齐用 raw×factor 重算，勿用 v_hfq 视图（视图有 2 位舍入）** |
| TASK-014 | data.api / universe | M1 | done | merged | 013 | review PASS；qlib init 竞态由审查者加锁修复 |
| TASK-015 | 增量日更 | M1 | done | merged | 013 | review PASS |
| TASK-016 | validate_vs_pg 黄金门 | M1 | done | merged | 013 | review PASS + 审查者修 itertuples `_merge` bug；M1 gate 报告见 docs/reviews/ |
| TASK-020 | tdx.functions + 黄金值 | M2 | done | merged | 004 | review PASS；KDJ 黄金全程精确；EMA 种子差异记入 021 |
| TASK-021 | KDJ + 双线 V2.1 | M2 | done | merged | 020 | 返工后 PASS；字面呼吸度语义经审查者恒等复核；v1 sorted 差异快照留档 |
| TASK-022 | B1 三版本 | M2 | done | merged | 021 | review PASS + 审查者 fixup 1e98259（or2 的 THREE_SUM 分支归属，A1 结构见 b1.md 修订注） |
| TASK-023 | 活跃市值 0AMV | M2 | done | merged | 020 | review PASS；924 行情信号复现 |
| TASK-024 | 倍量/单针/MACD/砖形 | M2 | done | merged | 021 | review PASS；brick zxt 黄金对齐 |
| TASK-025 | 事件研究引擎（gate 卡） | M2 | done | merged | 014, 021 | review PASS + 审查者三处口径修复后 10 股对拍**逐位归零**（2180=2180，0.0000bps）；M2 gate 见 docs/reviews/ |
| TASK-026 | IC / 分层分析 | M2 | done | merged | 025 | review PASS |
| TASK-060 | R1 研究基础设施（扫描/切分/稳定性） | R1 | done | merged | 025,026 | review PASS + 审查者修复：max_symbols 头部截断→种子化随机抽样（R1-batch1-review.md F-1） |
| TASK-061 | 研究：活跃市值（K/阈值/右侧确认） | R1 | done | merged | 060 | review PASS；审查者扩展 sell 网格（−1.0 内部极值）；候选=结构性 confirm_life@原版阈值（IS 累计 0.595 vs 0.310）；调参点按邻域判据弃用 |
| TASK-062 | 研究：B1 参数族+组合条件 | R1 | done | merged | 060 | review PASS；首轮 300 样本全为北交所股→作废，800 seed=42 重跑（findings 修订版为准）；case 网格的 stable 列不可采信（F-5） |
| TASK-063 | 研究：双线成对交易/退出策略 | R1 | done | merged | 060 | review PASS；真实样本 5250 笔：无退出规则击败原版死叉（PF 1.15、笔均 +0.93%、中位数负）；候选为空 |
| TASK-064 | 研究：单针/砖形 持有期×止损 | R1 | done | merged | 063 | review PASS + 审查者修 entry_low 止损入场日恒真 bug（F-2）；800 样本重跑后候选见 findings 修订版 |
| TASK-065 | 探索：红绿量占比/筹码代理有效性 | R1 | done | merged | 060 | review PASS + 审查者修 turnover 字段未加载假阴性（F-3）与单调性判定（F-4）；全部因子未过门槛，washout/turnover_cost 两家族留档 M6 |
| TASK-066 | R1 汇总：OOS 裁定+最终报告 | R1 | done | — | 061-065 | 规划者执行完毕：**R1 零候选进入 Tier3**（AMV confirm_life OOS 输基线不采纳）；报告 docs/reviews/R1-final-report.md；**R1 收官**（tag v2.0-r1） |
| TASK-067 | 工程债：qlib 批量 IO + CLI 守卫 | M3 | done | merged fae98f4 | — | review PASS；审查者独立复跑 branch=662s vs 基线 894s（1.35×，瓶颈=IC/分层/top-event 计算层，卡面条款豁免）；CSV 三方逐位一致；30 真实符号批量等价性精确相等 |
| TASK-068 | R1 协议一致性修复（入场严格 t+1 + 065 ashare） | R1 | done | merged | 067 | review PASS；审查者独立红灯复核（旧码 3 failed→新码全绿）+ 三卡 IS 同配置复跑数字与 findings 增补表逐项吻合；无结论翻转；OOS 勘误核对见 TASK-068-review.md |
| TASK-030 | qlib TopkDropout 基线 + mlflow | M3 | done | merged | 026 | review PASS（管线）；审查者双跑 67s 确定性逐位复核；**基线 metrics 判定无效**（universe 混入 258 个非股票代码，回撤 −116% 物理不可能）→ 根因在 TASK-011 分类兜底，修复卡 TASK-070；070 后重跑基线 |
| TASK-031 | bt costs/feed/constraints | M3 | done | merged | 014 | review PASS；审查者按 §3 独立复算全部费用字面量（5.01/5.51/26/76/6.01）+ cerebro 期末现金复算一致；-1 哨兵仅限 is_suspended、limit 缺失走 NaN→跳过（分层干净）；`set_trade_date` 提醒已写入 032 卡 |
| TASK-032 | DualTrend bt 移植 + parity | M3 | changes_requested | task/TASK-032-dualtrend-bt-parity | 031 | **第二轮返工项见 TASK-032-review.md 末节**：黄金参照已由审查者更换（2 月黄金在冻结 PG 上不可复现，223 条除权重算所致）——新黄金 `dualtrend_breath_full_20260710_124211_summary.csv`（v1 原码×冻结 PG，2015-01-01~2026-03-11，5305 只存活/97672 信号）；RSV 裁定=v1 字面 bt.If + engine 级 try/except 跳过（跳过语义即 v1 语义）；轴 B 维持；判据不变 |
| TASK-033 | PG 归档退役 | M3 | backlog | — | 016,025,032+gate | 016/025/032 三报告全绿 + 规划者写 M3-gate-report 后才置 ready（ADR-0002） |
| TASK-069 | 工程债：ruff format 全绿 | M3 | done | merged | 067,068 | review PASS；审查者逐字节验证 diff ≡ ruff format 输出（v2 原文件 format 后 cmp 全 IDENTICAL）；**质量门首次全绿**（88 files formatted） |
| TASK-070 | 数据卫生：证券分类兜底修复 | M3 | done | merged | 030 | review PASS；审查者红灯复核 + 独立复验 AC2/AC3；universe 5723→5465（恰 −258）；030 基线重跑有效（review 附录）；R1 敏感性复跑完毕→勘误 2（washout 单调性留档理由降级，零候选结论不变） |
| TASK-034 | AMV 组合级仓位开关（Tier2 overlay 预检） | M3 | done | merged | 030,070 | review PASS；审查者独立双跑 14 项 metrics 逐位一致 + regime 独立重建（exposure 0.4637/switches 96 逐位相同）+ base 与 030 附录逐位回归；**防御价值组合层复现**（mdd −2.25→−0.92、年化 −16.6%→+0.6%），系风险控制而非 alpha，Tier3 排位不变 |
| TASK-071 | 工程债：研究计算层向量化（IC/分层/top-event） | M3 | changes_requested | task/TASK-071-research-compute-vectorize | 067,068 | 第一轮裁定（TASK-071-review.md）：审查者独立双侧对照——**AC1 失败**（5/10 行 ic_mean/icir ULP 尾差=求和顺序漂移，须保序实现）；**AC2 基线误测**（88.73s 实为 cProfile 局部，审查者实测 v2≈12m）；分支侧 1m12s 测量正确，**真实加速 ≥7×**。修两项即过 |
| TASK-072 | 数据卫生：分类器号段补漏（302/201/395） | M3 | done | merged | 070 | review PASS；红灯复核 + 审查者独立复验 AC2/AC3（行数 12169、五板 3473/1433/608/560/166、universe 5466、302132 在内）；连带发现 turnover_cost w60 新样本翻 effective → R1 勘误 3（M6 留档优先级上调） |
| TASK-073 | 快照冻结 manifest + PG 归档 dump | M3 | ready | — | — | ADR-0005 §8：033 前置；dump+manifest 由本卡交付，恢复演练由规划者执行 |
| TASK-074 | 研究语义 LabelSpec（Tier1/IC 标签统一） | M3.5 | backlog | — | 071 | 白名单与 071 同碰 ic/forward_returns——071 合并后由规划者置 ready |
| TASK-075 | 稳定哈希抽样（universe 无关采样） | M3.5 | ready | — | — | 可并行开发；**合并排在 071 之后**（保 071 AC1 对照口径，规划者控制） |
| TASK-076 | trade_pairs 退出语义统一 + MAE/MFE 顺延 | M3.5 | in_progress | task/TASK-076-exit-semantics | — | 已认领；既有断言更新清单将在完成时补入此处。 |

推荐认领顺序：**032 二轮返工 ∥ 071 返工（均在原分支）优先**；073/075/076 三卡白名单互斥可并行认领（多卡并行时每张卡独立 worktree，见 TASK-072-review 备注）；074 等 071 合并后置 ready；033 由规划者在 032 过 + 三报告全绿 + 073 恢复演练通过后置 ready。**M3.5 已立项（ADR-0005）**：研究有效性加固，M4 可并行、M6 被其 gate 阻塞；R1 存档冻结，074/075/076 合并后旧研究数字不可复现属预期。M4–M6 的卡由规划者在对应里程碑开启时补写（标题级清单见 `docs/roadmap.md`）；R1 研究协议见 `docs/research/PLAN.md`（**开发代理只准碰 IS 段 2015–2021**）。

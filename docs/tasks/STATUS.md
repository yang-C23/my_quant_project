# STATUS.md — 任务看板（唯一状态源）

> 2026-10-20 用户批准实施重启总计划。当前任务 TASK-080，分支 task/TASK-080-trusted-index-restart。
> 使用 scripts/quant 固定当前工作树；总计划见 ../restart/MASTER_PLAN.md。
> 以下旧任务状态保留作为历史记录，旧“角色分流/只准IS”不约束已授权的新研究。

## 重启阶段

| 阶段 | 状态 | 证据/下一步 |
|---|---|---|
| 基线与审计 | inventory_complete / legacy_review_open | 初始代码/数据/73产物清单已冻结；关键路径语义修复见[审计](../restart/AUDIT.md)，旧策略未全部复现 |
| 工程与TDX修复 | implemented_and_tested | 独立环境、正确单位/份额拆分/公司行动、Decimal账本、243项离线测试通过；3项遗留集成测试未运行 |
| TDX更新 | structurally_accepted | 快照20261020T112255Z-2f1a3256f7；29,753,977行、12,490代码至10月19日；幂等、完整备份/隔离恢复通过 |
| 替代源验收 | partial / formal_gate_open | 已采集公开数据并交叉核查；长期估值、股息支付、许可/PIT和历史成分仍缺 |
| 基准及扩展回测 | price_diagnostics_reproduced / formal_blocked | 冻结120项假设；1,063条指数价格实验/窗口记录、2,999条暂停，精确重放通过；[结果及限制](../restart/RESULTS.md) |
| 每日监控 | shadow_timer_active | UTC 00:30/09:30用户定时器已启用；首次完整更新/计算成功；12标的暂停、0交易建议；重复执行不增加日期计数，20真实交易日未验收 |
| 长期维护 | ongoing | 文档与本机恢复具备；异地备份、正式数据晋级和未来20日验收待办 |

研究/部署代码提交为`66df912cc215af2d651efdeef3e6174afb5f0d0c`；后续纯文档提交不改变研究源码。
验收证据保存在`DATA_ROOT/audits/restart-acceptance-20261020/`，
汇总为`DATA_ROOT/audits/restart-acceptance-20261020.json`。
旧v1—v3快照及试跑保留；其ETF派生/原价绩效不能用于投资结论。

## 当前接手顺序

1. 读[交付映射](../restart/DELIVERY_MATRIX.md)和[来源档案](../restart/DATA_SOURCES.md)，补齐长期估值、完整公司行动/支付日、历史名录与留存依据；裁定跨源历史差异。
2. 数据准入通过后，接入版本化准入记录、公司行动及实际渠道执行模型；当前正式入口固定暂停，不能仅修改配置就当作已验收。
3. 完成PE两种退出、替代温度、恐慌/企稳、红利低波与风格组合的正式同窗口比较和最终样本外检验，再形成分标的操作规则。
4. 影子监控按实际更新继续累计；价格尚停在10月19日，启动日为10月20日，因此当前有效前瞻交易日计数为0。不得回填20日或把暂停当卖出。
5. 继续旧成果原版本复现、异地备份、来源变更及恢复演练；不把工程测试通过解释为完整研究验收。

## 旧任务存档

以下保留当时任务结论以便追溯。TASK-030/034中旧投资绩效口径已由本轮审计标为失效，
旧“防御价值”叙述不能代替重算后的投资结论；详见[审计报告](../restart/AUDIT.md)。

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
| TASK-032 | DualTrend bt 移植 + parity | M3 | changes_requested | task/TASK-032-dualtrend-bt-parity | 031 | **第三轮返工项见 TASK-032-review.md 末节 + 卡面修订节**：二轮交付合格（审查者逐位复现 −1069），根因三分=①v1 旗标空转（−371，审查者 run2 实证）②输入流逐 bar 不同（qfq 减法/乘法 + PG volume 复权，sh603019 零根相同）③920 段 PG 缺改码前历史（+87）；裁定按 M2 判例：PG 同源输入 parity（count 全等）+ qlib 输入差异量化归档；判据数字不变 |
| TASK-033 | PG 归档退役 | M3 | backlog | — | 016,025,032+gate | 016/025/032 三报告全绿 + 规划者写 M3-gate-report 后才置 ready（ADR-0002） |
| TASK-069 | 工程债：ruff format 全绿 | M3 | done | merged | 067,068 | review PASS；审查者逐字节验证 diff ≡ ruff format 输出（v2 原文件 format 后 cmp 全 IDENTICAL）；**质量门首次全绿**（88 files formatted） |
| TASK-070 | 数据卫生：证券分类兜底修复 | M3 | done | merged | 030 | review PASS；审查者红灯复核 + 独立复验 AC2/AC3；universe 5723→5465（恰 −258）；030 基线重跑有效（review 附录）；R1 敏感性复跑完毕→勘误 2（washout 单调性留档理由降级，零候选结论不变） |
| TASK-034 | AMV 组合级仓位开关（Tier2 overlay 预检） | M3 | done | merged | 030,070 | review PASS；审查者独立双跑 14 项 metrics 逐位一致 + regime 独立重建（exposure 0.4637/switches 96 逐位相同）+ base 与 030 附录逐位回归；**防御价值组合层复现**（mdd −2.25→−0.92、年化 −16.6%→+0.6%），系风险控制而非 alpha，Tier3 排位不变 |
| TASK-071 | 工程债：研究计算层向量化（IC/分层/top-event） | M3 | changes_requested | task/TASK-071-research-compute-vectorize | 067,068 | 第一轮裁定（TASK-071-review.md）：审查者独立双侧对照——**AC1 失败**（5/10 行 ic_mean/icir ULP 尾差=求和顺序漂移，须保序实现）；**AC2 基线误测**（88.73s 实为 cProfile 局部，审查者实测 v2≈12m）；分支侧 1m12s 测量正确，**真实加速 ≥7×**。修两项即过 |
| TASK-072 | 数据卫生：分类器号段补漏（302/201/395） | M3 | done | merged | 070 | review PASS；红灯复核 + 审查者独立复验 AC2/AC3（行数 12169、五板 3473/1433/608/560/166、universe 5466、302132 在内）；连带发现 turnover_cost w60 新样本翻 effective → R1 勘误 3（M6 留档优先级上调） |
| TASK-073 | 快照冻结 manifest + PG 归档 dump | M3 | changes_requested | task/TASK-073-snapshot-freeze | — | 第一轮裁定（TASK-073-review.md）：阻塞根因=worktree 缺 `.env`（tdx_home 落默认 /tdx），代码无错、协议执行正确；返工两项：①补 .env 重跑 AC2 freeze/verify；②verify 的 `_new_files` 全链重复 hash ~6 遍→只收集路径。dump 286M 已归档合格 |
| TASK-074 | 研究语义 LabelSpec（Tier1/IC 标签统一） | M3.5 | backlog | — | 071 | 白名单与 071 同碰 ic/forward_returns——071 合并后由规划者置 ready |
| TASK-075 | 稳定哈希抽样（universe 无关采样） | M3.5 | review | task/TASK-075-stable-hash-sampling | — | **review PASS（TASK-075-review.md），合并排队等 071 先合**——分支勿动；审查者已验：变形测试/均匀界/跨 PYTHONHASHSEED 逐位一致 |
| TASK-076 | trade_pairs 退出语义统一 + MAE/MFE 顺延 | M3.5 | done | merged ee18af8 | — | review PASS；审查者独立手算 AC1 全部期望值 + 红灯复核（旧码 4 failed→新码 15 passed）；退出语义与 Tier3 同构；R1 双线/短线存档自此不可复现（冻结）；审查中发现 editable install 跨 worktree 串扰风险→TASK-077 |
| TASK-077 | 工程债：worktree 测试隔离 + cli `__main__` 守卫 | M3.5 | ready | — | — | 源自 076 审查（editable 串扰假绿）与 F-7（`python -m quant.cli` 静默空跑）；白名单与在途卡零交集，可并行 |
| TASK-078 | 日度 PIT EligibilityPanel + UniverseProfile | M3.5 | ready | — | — | 用户需求落地（非ST/250交易日/ADV20 两档 3000万·1亿/close≥1）；**"未来收益完整"被裁定为前视，改标签层处理**；新模块零冲突可并行 |
| TASK-079 | UniverseProfile 接线（研究/Topk 入口） | M3.5 | backlog | — | 078,071,074,075 | 白名单与 071/075 在途分支同碰——依赖全合后由规划者置 ready 并复核 AC |

**以下为重启前的历史认领顺序，不作为当前排程：**

推荐认领顺序：**032 二轮返工 ∥ 071 返工（均在原分支）优先**；073/075/076 三卡白名单互斥可并行认领（多卡并行时每张卡独立 worktree，见 TASK-072-review 备注）；074 等 071 合并后置 ready；033 由规划者在 032 过 + 三报告全绿 + 073 恢复演练通过后置 ready。**M3.5 已立项（ADR-0005）**：研究有效性加固，M4 可并行、M6 被其 gate 阻塞；R1 存档冻结，074/075/076 合并后旧研究数字不可复现属预期。M4–M6 的卡由规划者在对应里程碑开启时补写（标题级清单见 `docs/roadmap.md`）；R1 研究协议见 `docs/research/PLAN.md`（**开发代理只准碰 IS 段 2015–2021**）。

## 当前授权任务

| ID | 状态 | 说明 |
|---|---|---|
| TASK-080 | in_progress | [任务卡](TASK-080-trusted-index-restart.md)，用户授权完整总计划 |

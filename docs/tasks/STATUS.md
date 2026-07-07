# STATUS.md — 任务看板（唯一状态源）

> 公告：当前开发环境 = `my_quant_env`（若 TASK-001 触发新建 `my_quant_v2`，由其 review 更新本行）。
> 状态机与流程见 `docs/workflow.md`；`backlog` 的卡不许认领。

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
| TASK-060 | R1 研究基础设施（扫描/切分/稳定性） | R1 | review | — | 025,026 | pytest -q tests/unit/test_optimize.py PASS；模板真实数据 demo <3m；IS 越界拒绝+按符号价格缓存已测 |
| TASK-061 | 研究：活跃市值（K/阈值/右侧确认） | R1 | backlog | — | 060 | |
| TASK-062 | 研究：B1 参数族+组合条件 | R1 | backlog | — | 060 | |
| TASK-063 | 研究：双线成对交易/退出策略 | R1 | backlog | — | 060 | |
| TASK-064 | 研究：单针/砖形 持有期×止损 | R1 | backlog | — | 063 | 复用 trade_pairs |
| TASK-065 | 探索：红绿量占比/筹码代理有效性 | R1 | backlog | — | 060 | 允许全负结论 |
| TASK-066 | R1 汇总：OOS 裁定+最终报告 | R1 | backlog | — | 061-065 | 规划者执行，不分配开发代理 |

M3–M6 的卡由规划者在对应里程碑开启时补写（标题级清单见 `docs/roadmap.md`）；R1 研究协议见 `docs/research/PLAN.md`（**开发代理只准碰 IS 段 2015–2021**）。

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
| TASK-011 | 元数据/标志位 staging | M1 | review | task/TASK-011-metadata | 010 | 返工：securities 分布 bond 970 / etf 2576 / index 2127 / stock main 3472 gem 1433 star 608 bse 560 b 165 other 258；other_sz002=0 |
| TASK-012 | 向量化复权因子 | M1 | backlog | — | 011 | |
| TASK-013 | qlib dump | M1 | backlog | — | 012 | |
| TASK-014 | data.api / universe | M1 | backlog | — | 013 | |
| TASK-015 | 增量日更 | M1 | backlog | — | 013 | |
| TASK-016 | validate_vs_pg 黄金门 | M1 | backlog | — | 013 | gate 工具 |
| TASK-020 | tdx.functions + 黄金值 | M2 | done | merged | 004 | review PASS；KDJ 黄金全程精确；EMA 种子差异记入 021 |
| TASK-021 | KDJ + 双线 V2.1 | M2 | review | task/TASK-021-kdj-dualtrend | 020 | 返工：RSV 除零=0；呼吸度改字面嵌套 rolling；v1 sorted 差异快照 sh600000 149/171 active 13、sz000001 171/171 active 40；53 tests+ruff+golden OK |
| TASK-022 | B1 三版本 | M2 | backlog | — | 021 | |
| TASK-023 | 活跃市值 0AMV | M2 | done | merged | 020 | review PASS；924 行情信号复现 |
| TASK-024 | 倍量/单针/MACD/砖形 | M2 | backlog | — | 021 | |
| TASK-025 | 事件研究引擎（gate 卡） | M2 | backlog | — | 014, 021 | parity 见 docs/parity |
| TASK-026 | IC / 分层分析 | M2 | backlog | — | 025 | |

M3–M6 的卡由规划者在对应里程碑开启时补写（标题级清单见 `docs/roadmap.md`）。

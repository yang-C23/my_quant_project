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
| TASK-012 | 向量化复权因子 | M1 | review | task/TASK-012-adjust | 011 | 9 target tests / 66 non-integration / ruff OK；PG sz000001 HFQ 8325 行 rtol≤1e-9；derive basics+adjust 各 28,673,235 行约 86s |
| TASK-013 | qlib dump | M1 | review | task/TASK-013-qlib-dump | 012 | stacked on 012；test_qlib_dump 2 passed / 68 non-integration / ruff OK；CLI subset dump sh600000 6280 rows, 16 fields, 12.7s |
| TASK-014 | data.api / universe | M1 | backlog | — | 013 | |
| TASK-015 | 增量日更 | M1 | backlog | — | 013 | |
| TASK-016 | validate_vs_pg 黄金门 | M1 | backlog | — | 013 | gate 工具 |
| TASK-020 | tdx.functions + 黄金值 | M2 | done | merged | 004 | review PASS；KDJ 黄金全程精确；EMA 种子差异记入 021 |
| TASK-021 | KDJ + 双线 V2.1 | M2 | done | merged | 020 | 返工后 PASS；字面呼吸度语义经审查者恒等复核；v1 sorted 差异快照留档 |
| TASK-022 | B1 三版本 | M2 | ready | — | 021 | 从最新 v2 切分支；长 fixture 规则见批次指令 |
| TASK-023 | 活跃市值 0AMV | M2 | done | merged | 020 | review PASS；924 行情信号复现 |
| TASK-024 | 倍量/单针/MACD/砖形 | M2 | ready | — | 021 | **堆叠**：从 task/TASK-022-b1 切出（共享 registry/__init__），022 置 review 后即开工 |
| TASK-025 | 事件研究引擎（gate 卡） | M2 | backlog | — | 014, 021 | parity 见 docs/parity |
| TASK-026 | IC / 分层分析 | M2 | backlog | — | 025 | |

M3–M6 的卡由规划者在对应里程碑开启时补写（标题级清单见 `docs/roadmap.md`）。

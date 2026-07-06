# TASK-010 Review（第 1 轮）

- 日期：2026-07-06　|　开发者 & 审查者：Claude (Fable 5)（本轮起替代 Codex，用户指示；自审模式下验收命令全部真实运行留痕）
- 分支：`task/TASK-010-staging-daily`（442cad4）

## 验收命令运行结果

| # | 命令 | 结果 |
|---|---|---|
| 1 | `pytest -q tests/unit/test_staging.py` | PASS（15+2 用例：v1 黄金逐值相等 ×3 符号、损坏记录跳过计数、端到端 staging、zip 抽取规范化+缓存、跨源并集 vipdoc 优先、collect/generate_symbol） |
| 2 | `ruff check .` + format | PASS |
| 3 | 集成：`myquant etl full --steps daily` + DuckDB 核数 | PASS：28,673,235 行 / 12,169 符号（卡面 ≥28M、≈12K ✓）/ 1990-12-19~2026-04-08 / (symbol,date) 零重复 / **41 秒**（预算 ≤5 分钟） |

## 范围修订（卡内已记录）

首次集成暴露卡面设计疏漏：vipdoc 仅含 ~2021-08 后数据（9M 行）。按规划者权限扩展：zip 全历史基线源（`extract_zip_baseline` + 按符号并集、vipdoc 优先去重 + `Settings.tdx_zip`）。修订已写入卡面"规划者修订"节与 data_platform.md §2。

## 质量意见

- 每符号一次 `drop_duplicates+sort` 在 worker 内完成，主进程流式写 zstd parquet——内存峰值可控，性能有大余量（解析+写仅 11.5s）。
- `sz200b07.day`（B股字母码）被文件名正则排除，与 v1 口径一致；B股不在平台范围。
- **数据时效发现**：vipdoc 最新数据为 2026-04-08——TDX 客户端已数月未下载行情，跑 M1 gate 对齐前无影响（PG 也冻结在旧日期），但日常使用需先在 Windows 侧 TDX 下载数据再 `myquant update`。

## 结论

**PASS** —— `--no-ff` 合并至 `v2`；TASK-011 置 `ready`。

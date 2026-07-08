# TASK-069: 工程债 — ruff format 全绿（既有文件格式化）

- Milestone: M3（工程债）　|　State: backlog
- Branch: `task/TASK-069-ruff-format-debt`　|　Depends: TASK-067, TASK-068

## Context
`ruff format --check .` 在 v2 上对 9 个既有文件报 "Would reformat"，使 CI 的
`ruff check . && ruff format --check .` 步骤实为红灯（M0 的"全绿"只覆盖 lint 与单测，
format 债是历史遗留）。其中 4 个（`research/exploratory.py`、`research/trade_pairs.py`、
`signals/factors.py`、`tests/unit/test_trade_pairs.py`）在 TASK-067/068 白名单内，会随其合并被
Codex 已格式化的版本覆盖而自动清零；本卡只清剩余 5 个无主文件。故 Depends 067、068。

## Goal
`ruff format --check .` 对整仓退出 0；纯格式化，零行为变更。

## Scope
对下列文件运行 `ruff format`，提交格式化结果。**不改逻辑、不改 ruff 配置、不动 `exclude` 列表。**

## Non-goals
不靠新增/删除 `exclude` 项来"绕过"检查；不重构；不碰 067/068 白名单内的 4 个文件（由那两卡清）。

## Files to touch
- `scripts/r1_oos_final.py`
- `src/quant/research/amv_timing.py`
- `src/quant/research/optimize.py`
- `tests/unit/test_amv_timing.py`
- `tests/unit/test_optimize.py`

## Acceptance criteria
1. `ruff format --check .` 退出码 0（整仓无 "Would reformat"）。
2. `ruff check .` 全绿。
3. `pytest -q -m "not integration"` 全绿（格式化不得改变行为）。
4. `git diff v2...HEAD -- scripts/r1_oos_final.py src/quant/research/amv_timing.py src/quant/research/optimize.py tests/unit/test_amv_timing.py tests/unit/test_optimize.py` 只含空白/换行/引号等格式差异，无逻辑改动。

## 验收如何被作弊/退化满足？
- 最大攻击面：把文件加进 `pyproject.toml` 的 ruff `exclude` 让 `--check` 假绿——**禁止**（Non-goals 已列）；审查者须对照 `pyproject.toml` 的 `exclude` 未被改动。
- 若 067/068 尚未合并，验收 1 会因那 4 个文件仍未格式化而失败——这正是 Depends 的意义：置 `ready` 前规划者确认 067/068 已 `done` 并重跑 `ruff format --check .` 取当前残余集，必要时更新本白名单。
- 格式化误伤行为：靠验收 3（pytest）+ 验收 4（diff 仅格式）双保险。

## Test plan
无新增单测（纯格式）。回归：现有单测不改断言全过。

## Notes / risks
- ruff 版本以 `.pre-commit-config.yaml`（v0.6.9）/ `pyproject.toml` 为准，本地与 CI 一致，避免版本差导致格式漂移。
- 置 `ready` 由规划者在 067、068 合并后执行（届时残余集可能已只剩这 5 个或更少）。

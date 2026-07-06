# TASK-004: 死代码与死依赖清理

- Milestone: M0　|　State: backlog
- Branch: `task/TASK-004-dead-code`　|　Depends: TASK-001

## Context
architecture.md §5 处置表。v1 遗留：已损坏的研究模块（import 不存在的函数）、被 pyproject 取代的 requirements.txt、过期文档。

## Goal
仓库中不再存在已知损坏/无引用的代码与过期文档；README 指向 v2 文档体系。

## Scope
**删除**（`git rm`）：
- `src/quant/research/kdj_b1_analysis.py`、`run_kdj_b1_analysis.py`（import 已不存在的 loader 函数，确认损坏）
- `run_backtest.py`、`run_dualtrend_breath_backtest.py`、`run_pipeline.py`、`src/quant/pipeline.py`（被 `myquant` CLI 取代；其中 kdj_j0 研究的参数已固化在 `configs/study_kdj_j0_parity.yaml`）
- `USAGE_GUIDE.md`、`configs/pipeline_prepare.yaml`、`configs/pipeline_kdj_j0.yaml`、`requirements.txt`
- `src/quant/indicators/brick.py` 中的 `BrickIndicator` 类（无引用；**保留同文件的 `TDXSMA`**——TASK-020 黄金值要用）

**改写**：`README.md` → 简短 v2 版：项目一句话、安装、`myquant` 命令表、指向 `docs/` 与 `AGENTS.md`/`CLAUDE.md`；保留"v1 历史见 main 分支"一句。

## Non-goals
不动 `scripts/{import_tdx,update_daily,calc_basic,calc_factor}.py` 与 `src/quant/db/`（冻结到 M3，TASK-033 删）；不动 `src/quant/backtest/`、`src/quant/data/loader.py`、`src/quant/reporting/`（后续卡重构）。

## Files to touch
上述删除/改写清单。

## Acceptance criteria
1. `pytest -q -m "not integration"` 与 `ruff check .` 全绿。
2. `python -c "import quant"` 成功；`grep -rn "kdj_b1_analysis" --include='*.py' .` 为空。
3. `git log --oneline -3` 删除动作为独立 commit。

## Test plan
无新测试；回归 = 现有 smoke + lint。

## Notes / risks
删 `pipeline.py` 前 `grep -rn "quant.pipeline\|from quant import pipeline"` 确认无引用；`BrickIndicator` 删除时保留文件头注释说明 TDXSMA 去向（TASK-020 会把整个文件挪进 tests/reference/）。

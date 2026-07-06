# TASK-002: GitHub Actions CI

- Milestone: M0　|　State: backlog
- Branch: `task/TASK-002-ci`　|　Depends: TASK-001

## Context
workflow.md（质量门）；roadmap.md Gate M0 要求 CI 全绿。

## Goal
push / PR 到 `v2` 时自动跑 lint + 单元测试 + qlib 冒烟。

## Scope
`.github/workflows/ci.yml`：
- 触发：push 到 `v2`、`task/**`；PR 到 `v2`。
- Job（ubuntu-latest, python 3.10，pip 缓存）：
  1. `pip install -e ".[dev]"`
  2. `ruff check . && ruff format --check .`
  3. `pytest -q -m "not integration" --cov=quant --cov-report=term`
- qlib 冒烟已含在 test_smoke.py 内，无需单列 step。

## Non-goals
不跑 integration 测试；不做发布/打包 job；不配矩阵多 Python 版本。

## Files to touch
`.github/workflows/ci.yml`(新)。

## Acceptance criteria
1. `git push origin task/TASK-002-ci` 后该分支 Actions 运行全绿（审查者在 GitHub 上核验）。
2. 本地 `act` 不要求；yml 通过 `python -c "import yaml,sys;yaml.safe_load(open('.github/workflows/ci.yml'))"`。

## Test plan
CI 运行本身即测试。

## Notes / risks
pyqlib 安装较慢（依赖 mlflow/pymongo 等）——务必启用 `actions/setup-python` 的 pip cache；如超 10 分钟考虑 `pip install pyqlib --no-deps` 变体，但需在 review 备注说明取舍。

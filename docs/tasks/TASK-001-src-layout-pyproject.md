# TASK-001: src 布局迁移 + pyproject.toml + 工具链

- Milestone: M0　|　State: ready
- Branch: `task/TASK-001-src-layout`　|　Depends: —

## Context
architecture.md §3（目标布局）、ADR-0004（git mv 独立提交）。v1 只有 requirements.txt，无打包/无 lint/无测试骨架。

## Goal
仓库变为可 `pip install -e ".[dev]"` 的 src 布局包，ruff/pytest 就绪，qlib 可导入。

## Scope
1. **移动提交（纯 git mv，不改内容，单独一个 commit）**：
   - `git mv quant src/quant`
   - `git mv scripts/tdx_parser.py src/quant/etl/tdx_parser.py`
   - `git mv scripts/gbbq_decoder.py src/quant/etl/gbbq.py`
   - `git mv scripts/blocks_parser.py src/quant/etl/blocks.py`
   - 新建空 `src/quant/etl/__init__.py`
2. **pyproject.toml**：name `my-quant`，requires-python `>=3.10`；deps（锁上界）：
   `pandas>=2.2,<3`, `numpy>=1.26`, `pyarrow>=16`, `duckdb>=1.0`, `pyqlib==0.9.7`,
   `backtrader>=1.9.78.123`, `pyyaml>=6`, `typer>=0.12`, `pydantic-settings>=2.4`, `tabulate>=0.9`;
   `[dev]`: `pytest>=8`, `pytest-cov`, `ruff>=0.6`, `pre-commit`。
   console script：`myquant = "quant.cli:app"`（cli.py 本卡先建最小骨架：typer app + `--version`）。
   ruff 配置（line-length 100）与 pytest 配置（markers: integration）写进 pyproject。
3. `.pre-commit-config.yaml`：ruff check + ruff format。
4. 修复移动后的 import（`quant/*` 内部相对引用不变；旧 `scripts/import_tdx.py` 等 sys.path 引用**允许失效**，见 Notes）。
5. `tests/unit/test_smoke.py`：`import quant`、`import qlib` 各一断言。
6. **环境验证**：优先在现有 `my_quant_env` 装；若 `pyqlib==0.9.7` 与现有 numpy/pandas 冲突或 import 失败，新建 conda env `my_quant_v2`（python=3.10，必要时 `numpy<2`），把最终环境名写进 STATUS.md 顶部公告与本卡 review 备注。**不许原地升级/降级 my_quant_env 的既有包。**

## Non-goals
不删任何文件（那是 TASK-004）；不写 CI（TASK-002）；不实现 config（TASK-003）；不动 `scripts/import_tdx.py` 等冻结脚本内容。

## Files to touch
`pyproject.toml`(新), `.pre-commit-config.yaml`(新), `src/**`(移动+新 __init__), `tests/unit/test_smoke.py`(新), `.gitignore`(追加 .env/exports 等), 移动涉及的 import 修正。

## Acceptance criteria
1. `pip install -e ".[dev]"` 成功（在最终选定 env）。
2. `python -c "import quant, qlib; print(qlib.__version__)"` 成功。
3. `pytest -q -m "not integration"` 全绿。
4. `ruff check . && ruff format --check .` 全绿。
5. `myquant --version` 输出版本。
6. `git log --oneline -5` 显示移动是独立 commit（信息含 "move-only"）。

## Test plan
仅 smoke 测试；工具链本身即验证对象。

## Notes / risks
- qlib 依赖重（mlflow 等），安装耗时正常；若 `import qlib` 报 numpy2 相关错，走新 env 阶梯（ADR-0001 风险条）。
- 移动后 `scripts/{import_tdx,update_daily,calc_basic,calc_factor}.py` 将因兄弟模块被移走而不可运行——**接受**：PG 已冻结（ADR-0002），它们只作算法参考留到 M3；在每个文件头加一行注释 `# FROZEN (v1 legacy): non-runnable since TASK-001; reference only until TASK-033.`（这是本卡对冻结脚本唯一允许的修改）。

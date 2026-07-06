# TASK-001 Review（第 1 轮）

- 日期：2026-07-06　|　审查者：Claude (Fable 5)　|　分支：`task/TASK-001-src-layout`（63543cf + e479b05）

## 验收命令重跑结果（审查者本机复跑）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `pip install -e ".[dev]"`（my_quant_env） | PASS |
| 2 | `python -c "import quant, qlib"` | PASS（quant 0.1.0 / qlib 0.9.7，现有 env 兼容，无需 my_quant_v2 回退） |
| 3 | `pytest -q -m "not integration"` | PASS（2 passed, 0.24s） |
| 4 | `ruff check . && ruff format --check .` | PASS（27 files formatted） |
| 5 | `myquant --version` | PASS（0.1.0） |
| 6 | 移动为独立 commit | PASS（63543cf，24×R100 纯改名 + 新空 `etl/__init__.py`，0 内容变更） |

## diff 审查

- **文件白名单**：符合。表面上 scripts/ 与 etl 模块出现整文件 diff，经 `--ignore-all-space` 核验为 **CRLF→LF 行尾规范化 + ruff 格式化**，实质变更仅：4 个冻结脚本各 +1 行授权的 FROZEN 头；`gbbq.py` 的 `from tdx_parser import` → `from quant.etl.tdx_parser import`（移动必需）；`tdx_parser.py` 删一个未用 `import os`；其余为换行/import 排序。无行为变化。
- **依赖**：pyproject 与卡中清单逐项一致，无未授权新增。
- **红线**：不涉及指标/回测逻辑，n/a。

## 备注（非阻塞，记入后续卡）

1. `[tool.ruff] exclude = ["run_*.py", "scripts"]`——当前合理（冻结遗留），但 **TASK-016 新增 `scripts/validate_vs_pg.py` 时须把排除收窄到四个冻结文件**，新脚本必须受 lint。已在 TASK-016 执行时由审查者把关。
2. git 身份沿用仓库历史惯例 `yang-C23 <yang@yang.localdomain>`（与 main 分支既有提交一致），不视为问题；如需改为 GitHub noreply 邮箱由用户决定。

## 结论

**PASS** —— `--no-ff` 合并至 `v2`；TASK-002/003/004（均仅依赖 001）置 `ready`。

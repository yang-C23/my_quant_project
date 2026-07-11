# TASK-077: 工程债 — worktree 测试隔离 + cli `__main__` 守卫

- Milestone: M3.5（工程债，白名单与全部在途卡零交集）　|　State: ready
- Branch: `task/TASK-077-worktree-test-isolation`　|　Depends: —

## Context
TASK-076 审查中发现：多 worktree 共享 conda env 时，`pip install -e` 的指向以最后一次
安装为准，在其他 worktree 跑 pytest 会 import 到**别的分支的代码**（审查者红灯复核一度
假绿）。另 R1-batch1-review F-7 记录：`src/quant/cli.py` 无 `__main__` 守卫，
`python -m quant.cli` 静默空跑（审查者本轮再次踩到）。

## Goal
每个 worktree 的 pytest 自动 import 本树的 `src/`；`python -m quant.cli --help` 正常输出
而非静默退出。

## Scope
1. `pyproject.toml` 的 `[tool.pytest.ini_options]` 增加 `pythonpath = ["src"]`
   （**本卡仅授权改这一节的这一项**，依赖/构建配置不动）；
2. `src/quant/cli.py` 末尾加：
   ```python
   if __name__ == "__main__":
       app()
   ```
3. 单测：`tests/unit/test_smoke.py` 增一条 `python -m quant.cli --version` 子进程冒烟
   （退出码 0 且输出非空）。

## Non-goals
不改 conda 环境管理；不动 CI；不迁移任何测试。

## Files to touch
- `pyproject.toml`
- `src/quant/cli.py`
- `tests/unit/test_smoke.py`

## Acceptance criteria
1. 在任一 worktree（不重新 pip install）：`pytest -q tests/unit/test_smoke.py` 全绿，且
   `pytest -q -c pyproject.toml --collect-only -q tests/unit/test_smoke.py >/dev/null && python -c "import sys; sys.path.insert(0,'src'); import quant; print(quant.__file__)"`
   打印**本 worktree** 路径；
2. `python -m quant.cli --version` 退出码 0 且输出版本号（改动前为静默空跑——红灯可复核）；
3. `pytest -q -m "not integration"` + `ruff check .` + `ruff format --check .` 全绿。

## 验收如何被作弊/退化满足？
1. **改 conftest 而非 pyproject**：效果类似但零散——白名单没有 conftest，会被拦；
2. **守卫加了但 app() 不被调**：AC2 子进程断言输出非空 + 退出码；
3. **pythonpath 写错键名静默无效**：AC1 断言 import 路径为本树。

## 数值验证类别与变形测试
n/a（纯工程配置，无数值面）。

## Test plan
smoke 子进程用例；AC1 由审查者在两个不同 worktree 各跑一次核对。

## Notes / risks
- `pythonpath` 需 pytest ≥ 7.0（仓库锁定版本满足）；
- editable install 仍存在，但 pytest 的 pythonpath 前置于 site-packages，本树优先。

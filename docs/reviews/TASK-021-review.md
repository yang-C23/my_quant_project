# TASK-021 Review（第 1 轮）

- 日期：2026-07-07　|　开发者 & 审查者：Codex（自审；验收命令真实运行留痕）
- 分支：`task/TASK-021-kdj-dualtrend`

## 验收命令运行结果

| # | 命令 | 结果 |
|---|---|---|
| 1 | `pytest -q tests/unit/test_kdj.py` | PASS（4 用例：两只黄金 fixture 全历史 K/D/J 对齐、除零 RSV NaN、`kdj_oversold` registry） |
| 2 | `pytest -q tests/unit/test_dual_trend.py` | PASS（7 用例：黄线全程对齐、白线 bar≥150 对齐、TDX EMA 种子、呼吸度重复量微用例、fixture 差异枚举、registry 重复保护） |
| 3 | `pytest -q -m "not integration"` | PASS（47 passed） |
| 4 | `python tests/fixtures/generate_goldens.py --check` | PASS（两只 bt_legacy golden 均 OK，200 rows） |
| 5 | `ruff check .` + `ruff format --check .` | PASS |

## 质量意见

- KDJ 直接组合 TASK-020 的 TDX 原语，`SMA` 递归语义与黄金值全程对齐。
- 双线白线采用 TDX `EMA(EMA(C,N1),N1)`，不沿用 bt classic EMA 的 SMA seed；测试按卡面规划者备注只在 bar≥150 与 bt golden 比较。
- 呼吸度按严格 `<` / `>` 的前三高/前三低去重口径向量化实现；当前两只 fixture 与 sorted 版黄金有效区间差异为 0 天，微用例覆盖重复量时会和 sorted 版分叉。
- registry 暴露 `get()` / `names()` / `register()`，内置 `kdj_oversold` 与 `dual_trend_entry`，重复注册会报错。

## 结论

**PASS** —— TASK-021 可进入 review；后续 TASK-022/TASK-025 可直接复用指标与信号入口。

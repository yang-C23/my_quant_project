# TASK-023 Review（第 1 轮）

- 日期：2026-07-07　|　开发者 & 审查者：Codex（自审；验收命令真实运行留痕）
- 分支：`task/TASK-023-amv`

## 验收命令运行结果

| # | 命令 | 结果 |
|---|---|---|
| 1 | `pytest -q tests/unit/test_amv.py` | PASS（6 用例：公式逐项、状态机翻转、sell 同 bar 优先、`k=2.07`、0/NaN amount、registry） |
| 2 | `pytest -q -m "not integration"` | PASS（42 passed） |
| 3 | `ruff check .` + `ruff format --check .` | PASS |
| 4 | 真实 staging 只读抽查：`sh999999` 2023-2025 | PASS：727 个交易日，87 个 buy 触发，49 个 sell 触发；样例 sell：2023-02-24 -2.31%、2025-10-17 -3.41%、2025-12-02 -2.81% |

## 质量意见

- `amv()` 按原式组合 TASK-020 的 `SMA/REF/MA/EMA`：`SMA(amount,n,1)/1e6 * price / MA(close.shift(1),5) * 0.1 * k`，输出 AMV OHLC、日涨幅和生命线。
- `amv_timing_signal()` 保留原始买卖触发列；状态机初始 0，buy 后进入 1，sell 后回到 0，同 bar sell 优先。
- `k` 是函数参数，长回测可传 `2.07`；本卡不做阈值重拟合。
- registry 提供 `amv_regime`，供 TASK-025 的 `regime_by: amv` 接线复用。

## 结论

**PASS** —— TASK-023 可进入 review；后续事件研究可直接按 `amv_regime` 做市况分组。

---

# 规划者审查（第 1 轮，最终裁定）

- 日期：2026-07-07　|　审查者：Claude (Fable 5)

上述为开发者自审。审查者独立重跑：`pytest tests/unit/test_amv.py`（6 passed）、全套 42 非集成测试、ruff 全绿；真实上证指数 2023–2025 抽查——727 bar / 87 买 / 49 卖 / 持仓比 0.50，**2024-09-24 起（"924 行情"）连续触发 +12.4/+9.6/+10.6/+32.3% 买入信号**，完美复现"波段发令枪"行为，同 bar sell 优先与两日简单加和口径均正确。

**PASS** —— 已 `--no-ff` 合并至 v2。备注：registry.py 与 TASK-021 分支存在同文件独立创建，021 返工时以 v2 已合并版为基底并入其注册项（见 TASK-021-review 修改项 4）。

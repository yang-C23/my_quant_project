# TASK-067: 工程债 — qlib 批量 IO + CLI 入口守卫

- Milestone: M3（前置工程债）　|　State: ready
- Branch: `task/TASK-067-io-batch-cli-guard`　|　Depends: —

## Context
R1 实测研究单卡（800 股）逐符号 qlib IO 6–15 分钟。根因：`quant.data.api.get_ohlcv` 单符号一次 `D.features`，qfq 模式还要 `_latest_factor` 额外全历史查一次 `$factor`；研究链每符号 qfq+raw 双载 = ~4 次 qlib 调用/符号。`get_features` 本身已支持多符号，浪费在调用方式。另：`src/quant/cli.py` 缺 `__main__` 守卫，`python -m quant.cli` 静默空跑（退出码 0、无输出），是入口陷阱。

## Goal
研究/study 数据加载走批量 qlib IO（数值与逐符号路径逐位一致），800 股研究卡的加载时间下降一个量级级别；`python -m quant.cli` 行为与 `myquant` 一致。

## Scope
```python
# src/quant/data/api.py 新增
def get_ohlcv_batch(
    symbols: Sequence[str],
    start: str | None = None,
    end: str | None = None,
    *,
    adjust: Literal["qfq", "hfq", "raw"] = "qfq",
    fields: Sequence[str] | None = None,
) -> pd.DataFrame:
    """单次（qfq 为两次：数据+全区间 $factor 取各符号末值）D.features 调用加载多符号。
    返回长表，列 = [symbol, date, <fields...>]，按 (symbol, date) 排序。
    数值必须与逐符号 get_ohlcv 完全一致（含 qfq 的 per-symbol latest factor 语义）。
    窗口内无数据的符号静默缺席（调用方等价于现在的 except ValueError: continue）。"""
```
重接以下调用点为批量加载（**只改 IO 方式，行为/数值零变化**）：
1. `research/forward_returns.py::_load_prices`（qfq open/close + raw open/suspended/limit_up 两次 batch，替代 ThreadPool 逐符号，join 口径不变）；
2. `research/trade_pairs.py`：`run_dual_trend_research` 与 `_shortterm_inputs` 改为先 batch 载价（qfq 全字段 + raw 旗标），再按 symbol groupby 逐符号算指标；`_load_prices(symbol,…)` 可改造或退役；
3. `research/exploratory.py::_load_prices`；
4. `signals/factors.py::compute_signal / compute_factor_frame`：IO 批量化（指标计算仍逐符号）；ThreadPool 保留与否由实现取舍，但 qlib 调用次数必须与符号数解耦。

CLI：`src/quant/cli.py` 末尾加 `if __name__ == "__main__": app()`。

## Non-goals
不改任何研究/信号数值结论；不动 `optimize.py`（已有按符号缓存）；不做 qlib 表达式级重构；不碰 OOS；不引入新依赖。

## Files to touch
`src/quant/data/api.py`, `src/quant/research/forward_returns.py`, `src/quant/research/trade_pairs.py`, `src/quant/research/exploratory.py`, `src/quant/signals/factors.py`, `src/quant/cli.py`, `tests/unit/test_data_api.py`, `tests/integration/test_data_api_real.py`, `tests/unit/test_forward_returns.py`, `tests/unit/test_trade_pairs.py`（如口径需适配）。

## Acceptance criteria
1. `pytest -q tests/integration/test_data_api_real.py -m integration`：新增等价性用例——真实数据 seed 抽样 ≥30 符号（必须含至少 1 只期内退市/长停牌股），`get_ohlcv_batch` vs 逐符号 `get_ohlcv` 在 qfq/hfq/raw × 全字段下 `assert_frame_equal`（**精确相等，无容差**）。
2. 性能对比：认领后先在 `v2` 基线 `time myquant research configs/research/exploratory.yaml` 记录耗时，再在任务分支同命令复测；目标 ≥3× 加速，两个耗时数字写入 STATUS 备注。不达标不算失败，但必须附瓶颈分析（哪一段仍是热点）。
3. 结果不变性：任务分支重跑 `myquant research configs/research/exploratory.yaml`，输出 csv 与基线运行**逐位一致**（`diff` 两份 `*_exploratory.csv`）。
4. `/home/yang/venvs/my_quant_env/bin/python -m quant.cli --help` 退出码 0 且列出 etl/dump/study/research/ic/update/validate；`myquant --help` 无回归。
5. `pytest -q -m "not integration"` + `ruff check .` 全绿。

## Test plan
单测：batch 长表 → 单符号切片与 get_ohlcv 输出结构等价（用现有 fixture）；qfq latest-factor 批量取值逻辑单测。集成：验收 1。回归：现有 forward_returns / trade_pairs 单测不改断言全过。

## Notes / risks
- qfq 的 `_latest_factor` 语义 = 不限窗口的最新 factor；批量实现用一次全区间 `$factor` 查询 groupby last，注意与单符号路径在"窗口外仍有数据"的符号上保持一致。
- `D.features` 多符号返回 MultiIndex(instrument, datetime)；符号名大小写转换沿用 `to_qlib/from_qlib`。
- 本卡与 TASK-068 共享 trade_pairs/exploratory 白名单，已用 Depends 串行化（068 等本卡合并）。

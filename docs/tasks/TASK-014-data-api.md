# TASK-014: quant.data — 统一数据访问 API / universe / 符号规范

- Milestone: M1　|　State: backlog
- Branch: `task/TASK-014-data-api`　|　Depends: TASK-013

## Context
architecture.md §2（data 层职责：下游唯一数据入口）；conventions.md（符号/日期约定）。

## Goal
下游（indicators/research/backtest/dashboard）只 import `quant.data`，不直接触碰 qlib provider 或 staging 路径。

## Scope
```python
# src/quant/data/symbols.py
def to_qlib(symbol: str) -> str            # sh600000 → SH600000；us:AAPL → AAPL(us region)
def from_qlib(instrument: str) -> str
def exchange_of(symbol: str) -> str        # sh|sz|bj|us
def board_of(symbol: str) -> str           # main|gem|star|bse|index（前缀规则同 TASK-011）

# src/quant/data/api.py
def init_qlib(region: str = "cn", freq: str = "day") -> None      # 幂等；从 settings 取 uri
def get_ohlcv(symbol: str, start: str | None = None, end: str | None = None,
              *, adjust: Literal["qfq","hfq","raw"] = "qfq", freq: str = "day",
              fields: Sequence[str] | None = None) -> pd.DataFrame
    """index=DatetimeIndex(date)；列 open,high,low,close,volume,amount,factor(+可选扩展字段)。
    hfq=bin 原值；raw=价/factor、量×factor；qfq=hfq/latest_factor（末日=现价口径）。"""
def get_features(symbols: Sequence[str], fields: Sequence[str],
                 start=None, end=None) -> pd.DataFrame               # 透传 D.features，多符号

# src/quant/data/universe.py
def list_symbols(*, sec_type: str = "stock", exclude_boards: set[str] = frozenset({"star"}),
                 min_float_mktcap: float | None = None, at: str | None = None) -> list[str]
    """基于 instruments PIT 区间 + staging securities/basics；at=历史某日的时点宇宙。"""
```

## Non-goals
分钟/美股实现（接口 freq/region 参数留好即可）；缓存层。

## Files to touch
`src/quant/data/{__init__.py,api.py,universe.py,symbols.py}`, `tests/unit/test_symbols.py`, `tests/unit/test_data_api.py`(用 TASK-013 的迷你 qlib fixture), `tests/integration/test_data_api_real.py`。

## Acceptance criteria
1. `pytest -q tests/unit/test_symbols.py tests/unit/test_data_api.py` 全绿：三种 adjust 口径换算恒等式（`raw*factor==hfq`、`qfq==hfq/last_factor`）在 fixture 上成立；符号互转往返一致；board 前缀表驱动全覆盖。
2. 集成：`python -c "from quant.data.api import get_ohlcv; df=get_ohlcv('sz000001', start='2024-01-01'); print(df.tail())"` 输出合理；`list_symbols(exclude_boards={'star','bse'})` 数量与 PG 同口径一致（±0）。
3. `ruff` 全绿。

## Test plan
如上 + 退市股查询（区间截断）、空结果快速失败（明确异常信息）。

## Notes / risks
qfq 的"末日=现价"口径意味着**qfq 值随数据更新漂移**——研究层重现实验须用 hfq 或记录数据快照日期（写入 api docstring 与 data_platform.md 交叉引用）。

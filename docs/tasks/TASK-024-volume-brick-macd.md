# TASK-024: 指标移植 — 倍量柱/单针下20(代理) + 知行MACD + 砖形振荡器

- Milestone: M2　|　State: backlog
- Branch: `task/TASK-024-volume-brick`　|　Depends: TASK-021

## Context
docs/indicators/volume_patterns.md（规则量化表 + 代理版声明）、zhixing_macd.md、brick.md（三变体逐字公式 + 执行规则）。

## Goal
其余全部笔记指标落地为可注册信号，黄金值/微用例锁定。

## Scope
```python
# src/quant/indicators/volume_patterns.py
def volume_patterns(df, *, dv_ratio=2.0, half_ratio=0.5, dead_window=60) -> pd.DataFrame
    # 列：sig_double_vol_yang, sig_dvy_sandwich, sig_triple_dvy, sig_half_down,
    #     sig_dead_vol, sig_dvy_distribution, washout_area_ratio —— 语义见 volume_patterns.md 表
def single_needle_proxy(df, *, shrink_ratio=0.5, shadow_body_ratio=2.0, dip_pct=0.03) -> pd.DataFrame
    # 代理版（文档已声明与指南针原版的差异）；列 sig_single_needle

# src/quant/indicators/zhixing_macd.py
def zhixing_macd(df) -> pd.DataFrame   # diff,dea,macd,sig_diff_cross_up_zero,sig_diff_cross_dn_zero

# src/quant/indicators/brick_osc.py
@dataclass(frozen=True)
class BrickParams: ...                 # strict / relaxed / len_checked 三预设（brick.md 变体表）
def brick_osc(df, params=PRESETS["strict"]) -> pd.DataFrame
    # 列：zxt, brick_delta, sig_brick_turn, sig_brick_<preset>
```
- registry 注册：`double_vol_yang, triple_dvy, single_needle_proxy, zhixing_macd_cross, brick_strict, brick_relaxed, brick_len`。

## Non-goals
策略层执行规则（止损/持仓天数——进 M3 bt 策略或 M6 研究）；指南针资金线精确版。

## Files to touch
`src/quant/indicators/{volume_patterns.py,zhixing_macd.py,brick_osc.py}`, `src/quant/signals/registry.py`, `tests/unit/test_volume_patterns.py`, `tests/unit/test_zhixing_macd.py`, `tests/unit/test_brick.py`。

## Acceptance criteria
1. `pytest -q` 三个测试文件全绿：
   - brick：`zxt` vs TASK-020 黄金 `brick_*.csv` rtol ≤ 1e-8；三变体条件微用例（TURN/STRONG/GOK/ROK/SUP/OSD 各自触发与不触发）；
   - volume：手算微用例（倍量三明治窗口边界：回调 2 天 vs 4 天；三连倍量的量价齐升要求）；
   - macd：diff/dea vs pandas ewm(adjust=False) 手算 rtol 1e-10，零轴 cross 布尔快照。
2. `ruff` 全绿。

## Test plan
如上 + fixture 全历史命中日 snapshot（同 TASK-022 模式）。

## Notes / risks
- brick 变体二/三的 D 与 KDJ 的 D 重名（brick.md 移植要点）——实现内部命名区分。
- `sig_dvy_sandwich`/`sig_triple_dvy` 的信号日=形态完成日（最后一根倍量阳），不许前视。
- 单针代理版 docstring 必须声明"proxy, 与笔记原版（指南针资金线）不等价；先验：胜率~37%、盈亏比 3:1"。

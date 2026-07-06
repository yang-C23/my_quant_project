# TASK-022: 指标移植 — B1 选股（三版本参数化）

- Milestone: M2　|　State: backlog
- Branch: `task/TASK-022-b1`　|　Depends: TASK-021

## Context
docs/indicators/b1.md（v2.42.62 逐字公式 + 版本差异表 + 构件语义 + 移植要点）。

## Goal
单一参数化 B1 实现 + 三组预设，构件级可测试，`sig_b1` 可入事件研究。

## Scope
```python
# src/quant/indicators/b1.py
@dataclass(frozen=True)
class B1Params:
    yangyin_windows: tuple[tuple[int, float], ...]   # ((28,1.4),(14,2.0),(57,1.2)) for v2.42.62
    yangyin_mode: Literal["and3", "or2"]             # .62: (ok1&ok3)|(ok2&ok3)；b/p: ok1|ok2 —— 见差异表
    cnt_bad_window: int                              # 14 | 21
    plry_long_count: int                             # 3 | 4
    three_sum_window: int                            # 28 | 57
    three_sum_min: int                               # 2 | 3 | 4
    maxvol_window: int                               # 14 | 28
    line_mult: float                                 # 0.995 | 0.985
    j_max: float = 13.0

PRESETS: dict[str, B1Params]   # b1_v242_62（默认）/ b1_v242b / b1_v242p，值照差异表逐格核对

def b1(df: pd.DataFrame, params: B1Params = PRESETS["b1_v242_62"]) -> pd.DataFrame
    # 输出构件列：real_yang, real_yin, j, plry, plry_cnt_ok, yangyin_ok*, good_cnt_ok,
    #            three_sum_ok, maxvol_ok, hm_short, hm_long, a1, sig_b1
    # 注意：MV（市值）与板块剔除不在本函数内（signals/universe 层），b1.md 移植要点 1/5
```
- `signals/registry.py` 注册 `b1_v242_62 / b1_v242b / b1_v242p`（含 universe 侧 `min_float_mktcap=50e8` 的组合封装，放 `signals/factors.py` 或 registry 组合器，签名由实现者定但需在 docstring 写明市值过滤发生处）。

## Non-goals
B2/B3 序列逻辑（策略层，M3+ 研究卡）；参数寻优。

## Files to touch
`src/quant/indicators/b1.py`, `src/quant/signals/{registry.py,factors.py}`, `tests/unit/test_b1.py`。

## Acceptance criteria
1. `pytest -q tests/unit/test_b1.py` 全绿，至少包含：
   - **构件微用例**（合成 bar 序列）：REAL_YANG/REAL_YIN 边界（平昨收、平开）、PLRY 三条件、HALF_DOWN 前提（前一日非实体阴）、GOOD28 的 TOP15O∧FD15 触发、MAX14_BAD；
   - 三预设参数与 b1.md 差异表逐格断言（防抄错数字）；
   - HMSHORTWL 双递归 SMA vs `tdx.functions` 组合调用一致（rtol 1e-12）；
   - fixture 股票全历史 `sig_b1` 命中日快照测试（首次运行生成 snapshot 提交，此后回归比对）。
2. `ruff` 全绿。

## Test plan
如上。命中日 snapshot 是回归锚：任何后续重构导致命中集变化都会被抓住。

## Notes / risks
- v2.42.62 的 A1 两分支都含 YANGYIN_OK3——`yangyin_mode` 的抽象要能表达三个版本的布尔结构，写不干净宁可用三个小函数组合，别造复杂 DSL。
- warmup >160 根，fixture 需足够长（TASK-010 的 200 根勉强够，不够就加长 fixture 并更新黄金值，在 README 记录）。

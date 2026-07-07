# TASK-060: 研究基础设施 — 参数扫描 / IS-OOS 切分 / 稳定性检验

- Milestone: R1　|　State: ready
- Branch: `task/TASK-060-research-infra`　|　Depends: TASK-025, TASK-026（已合并）

## Context
docs/research/PLAN.md §1–2（协议全文）。后续 061–065 全部跑在本卡的 runner 上。

## Goal
`myquant research configs/research/<name>.yaml` 一条命令完成一个指标的 IS 参数扫描 + 稳定性检验 + 报告。

## Scope
```python
# src/quant/research/optimize.py
@dataclass(frozen=True)
class ScanResult:
    table: pd.DataFrame        # 每参数组合一行：params…, signals_per_year, h1/h3/h5/h10/h20 的
                               # avg/win/profit_factor, rank_ic_5, icir_5, regime0_h5_avg, regime1_h5_avg
    top: pd.DataFrame          # 按目标函数排序 top-5 + 邻域稳定性判定列
    baseline: pd.Series        # z哥原版参数同口径一行

def run_param_scan(cfg: ResearchConfig) -> ScanResult
    """对 cfg.grid 的笛卡尔积逐组：compute_signal(签名与 registry 对齐的参数化信号)
    → run_event_study(IS 区间, entry_filters=ashare) [+ 可选 to_factor→rank_ic]
    → 汇总一行。信号计算结果按参数键缓存（同一符号价格只加载一次）。"""

def neighborhood_stability(table, params_grid, best, *, metric="h5_avg", floor=0.7) -> pd.DataFrame
    """PLAN §2 判据：best 的全部 ±1 步邻居 metric ≥ floor×best 且邻域中位数>基线。"""

def write_scan_report(result, out_dir) -> Path   # md：网格热区表、top-5、稳定性、regime 分层、密度
```
- **configs/research/ 的 yaml schema**（写进模板 `configs/research/_TEMPLATE.yaml`）：
  `signal`（registry 名或参数化构造器）、`grid:{参数:[候选值]}`、`baseline:{参数:值}`、
  `is_start/is_end`（默认 2015-01-01/2021-12-31，**yaml 不允许出现 2022 之后的日期**——runner 校验并拒绝）、
  `horizons`、`objective`（默认 h5_avg×profit_factor 排序键，可配）、`ic: true|false`。
- CLI：`myquant research <cfg>`；输出 `backtest_results/research/<name>_scan.{csv,md}`。
- **regime 接线**：`run_event_study(regime=...)` 已支持——本卡把 `amv_regime`（对上证指数计算）自动注入 study/research 两条链（cli 的 `regime_by: amv` 生效）。
- **OOS 保护**：runner 硬编码拒绝 `is_end > 2021-12-31`；OOS 评估走独立入口 `myquant research <cfg> --oos-final params.json`（打印醒目警告并要求 `--i-am-the-reviewer` 标志）——机制性防偷看。

## Non-goals
各指标的具体研究（061–065）；ML 寻优（网格即可）；分布式并行。

## Files to touch
`src/quant/research/optimize.py`, `src/quant/cli.py`, `configs/research/_TEMPLATE.yaml`, `tests/unit/test_optimize.py`, `docs/research/PLAN.md`(如 schema 细节需修订).

## Acceptance criteria
1. `pytest -q tests/unit/test_optimize.py`：合成价格+已知最优参数的迷你网格 → top 表正确；邻域悬崖用例（构造一个尖峰参数点）被正确拒绝；`is_end` 越界 yaml 被拒绝。
2. `myquant research configs/research/_TEMPLATE.yaml`（模板用 kdj_oversold j_threshold 网格 [0,5,13,20,26.5]，10 只股票 demo 宇宙）在真实数据上出报告 ≤ 3 分钟。
3. ruff/全套非集成绿。

## Notes / risks
- 扫描性能：先按符号加载一次价格并缓存，再对参数循环（信号计算是纯内存 pandas，快）；禁止每参数组合重复走 qlib IO。
- 目标函数默认值是初始约定，061+ 各卡可覆盖，但必须在配置里显式声明。

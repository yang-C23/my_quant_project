# TASK-030: qlib TopkDropout 组合回测基线 + mlflow

- Milestone: M3　|　State: ready
- Branch: `task/TASK-030-qlib-topk-baseline`　|　Depends: TASK-026（已合并）

## Context
`docs/backtest_platform.md` §1 Tier2、§4；ADR-0001。目的：打通"registry 信号/因子 → qlib 因子 → TopkDropoutStrategy → 含费组合回测 → mlflow 跟踪"的完整管线。这是 Tier3 之前的组合层，也是 R1 裁定的 Tier3 首个验证对象（AMV 原版 immediate 组合级仓位开关，后续 TASK-034）要挂载的宿主。本卡验证管线，不追求因子 alpha。

## Goal
`myquant backtest topk configs/backtest/topk_baseline.yaml` 一条命令完成全市场组合回测，指标落 mlflow（`DATA_ROOT/mlruns`），报告落 `backtest_results/backtest/`。

## Scope
```python
# src/quant/backtest/qlib_topk.py
@dataclass(frozen=True)
class TopkResult:
    metrics: dict[str, float]        # annualized_return, information_ratio, max_drawdown,
                                     # turnover_mean, excess_return_wo_cost/with_cost（qlib 口径）
    report_paths: dict[str, Path]    # csv + md
    mlflow_run_id: str

def run_topk_backtest(config_path: str | Path) -> TopkResult:
    """yaml → 因子（signal 经 to_factor 编码 {1.0,0.0}，或 factor 经 compute_factor_frame）
    → TopkDropoutStrategy(topk, n_drop) → qlib backtest（exchange 见下）→ mlflow + 报告。"""
```
- **配置 schema**（`configs/backtest/topk_baseline.yaml`，含注释）：`name`、`kind: signal|factor`、`score`（registry 名）、`start/end`、`universe`（默认 `list_symbols(exclude_boards={"star","b"}, at=None)`）、`topk`(默认 50)、`n_drop`(默认 5)、`benchmark`（默认 sh000001）、`exchange:{open_cost,close_cost,min_cost,limit_threshold}`。
- **基线因子**：在 `signals/factors.py` 注册连续因子 `mom_20`（`close.pct_change(20)`，qfq），基线配置 `kind: factor, score: mom_20`。布尔信号打分平局多，不适合做 rank 基线。
- **exchange（Tier2 近似口径）**：`open_cost=0.0005, close_cost=0.0015, min_cost=5, limit_threshold=0.095`——佣金万2.5+过户+滑点、卖含印花的一刀切近似；精确分板/T+1 是 Tier3（TASK-031）职责。口径写入报告头。
- **mlflow**：tracking uri = `get_settings()` 下的 `DATA_ROOT/mlruns`（新增 settings 字段），experiment=`topk_baseline`；记录全部 config params + metrics。mlflow 依赖入 pyproject（qlib 0.9.7 已依赖 mlflow，确认锁版即可）。
- **CLI**：`cli.py` 新增 `backtest` 子 app，命令 `myquant backtest topk <cfg>`。
- 基线区间取 IS 窗口 2015-01-01 ~ 2021-12-31（平台卡不受 R1 网格约束，但避免在 Tier3 裁定前消费 OOS/封存段信息）。

## Non-goals
新策略/新因子研究（mom_20 仅作管线基线，不下结论）；ML 模型（M6）；分板涨跌停与 T+1 精确约束（TASK-031）；AMV regime 开关（后续卡）。

## Files to touch
`src/quant/backtest/qlib_topk.py`, `src/quant/backtest/__init__.py`, `src/quant/signals/factors.py`（仅 +mom_20）, `src/quant/cli.py`, `src/quant/config.py`（mlruns 路径字段）, `configs/backtest/topk_baseline.yaml`, `pyproject.toml`（如需显式 mlflow）, `tests/unit/test_qlib_topk.py`。

## Acceptance criteria
1. `myquant backtest topk configs/backtest/topk_baseline.yaml` 全市场 IS 区间跑通，打印 metrics 与报告路径；耗时记入 STATUS 备注（预期分钟级）。
2. `/home/yang/venvs/my_quant_env/bin/python -c "import mlflow; c=mlflow.MlflowClient(tracking_uri='<DATA_ROOT>/mlruns'); r=c.search_runs(c.get_experiment_by_name('topk_baseline').experiment_id); print(r[0].info.run_id, r[0].data.metrics)"` 能列出该 run 与指标。
3. 同配置重跑两次，metrics 逐位一致（确定性；qlib/numpy 随机源固定）。
4. `pytest -q tests/unit/test_qlib_topk.py`：配置解析/校验、因子编码（signal→{1,0}、factor→float、index=(datetime,instrument)）、exchange kwargs 构造；qlib 回测本体不 mock 进单测（集成级由验收 1 覆盖）。
5. `pytest -q -m "not integration"` + `ruff check .` 全绿。

## 验收如何被作弊/退化满足？

1. **缩水配置跑通**：config 由本卡新建（在白名单内），universe 缩成 10 只/窗口缩成 3 个月也能让 AC1"跑通"——审查者将核对 `topk_baseline.yaml` = 卡面默认（全市场 universe、2015–2021、topk=50、卡面费率四元组），任何偏离须书面理由。
2. **确定性假验证**：AC3 若只读同一份报告两遍即"逐位一致"——必须是**两次完整命令调用**，mlflow 出现两个不同 run_id 且 metrics 逐位相同。
3. **mlflow 手灌指标**：AC2 可用 `mlflow.log_metric` 手写数字而与回测脱钩——审查者将比对 mlflow metrics 与报告 CSV 的 qlib 原生输出是否同源一致。
4. **费率归零美化**：exchange 成本调低可让基线数字变好并绕开 qlib 成本路径——费率以卡面数字为准并写入报告头，审查逐项核对。
5. **mom_20 未来函数**：实现若混入 `shift(-1)`/未来窗口即违反红线——沿用 065 的 look-ahead 单测模式（尾行扰动不改历史值）。
6. **绕开批量 IO**：因子计算绕过 `compute_factor_frame` 手写逐符号 qlib 调用 = 静默回退 067 成果——审查者 diff 检查 IO 路径。

## Test plan
单测聚焦纯函数（config → 组件参数）；真实回测走验收 1/3。fixtures 用合成因子 Series 验证编码与 index 约定。

## Notes / risks
- qlib 0.9.7 的 `backtest_daily` / `TopkDropoutStrategy` 用 `signal=pd.Series(index=(datetime,instrument))` 直喂即可，不必造 Model/Dataset；如 API 需要 `(model,dataset)` 形态，用 `SignalStrategy` 的 signal 参数路径，卡内不许为此引入 handler 层。
- benchmark 指数收益从 qlib cn_daily 的 sh000001 取；若 index 数据缺字段，报告里显式说明。
- `D.features` 全市场按需字段加载，注意别把 067 的批量化成果绕开（因子计算走 `compute_factor_frame`）。

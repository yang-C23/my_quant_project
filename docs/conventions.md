# conventions.md — 工程约定

## 代码

- Python ≥ 3.10；src 布局（`src/quant/`）；包名 `quant`，安装名 `my-quant`。
- Lint/format：ruff（规则与格式配置集中在 `pyproject.toml`；line-length 100）。
- 类型注解：公共函数必须有；`from __future__ import annotations` 统一开启。
- 日志用 `logging.getLogger(__name__)`；禁止 `print`（CLI 用户输出经 typer/rich 除外）。
- 向量化优先：全市场级数据处理禁止逐行 Python 循环；递归型语义（TDX SMA/EMA）允许每符号一次 `numba`/纯 numpy 递推，但外层必须 groupby 向量化组织。
- 异常策略：ETL 对单文件/单符号失败 warn+跳过并计数，最终汇总报告；研究层对空数据快速失败。

## 命名与单位

- 符号：内部一律小写 `sh600000` / `sz000001` / `bj830799`；qlib 侧 `SH600000`；美股内部 `us:AAPL`。互转只用 `quant.data.symbols`。
- 日期：`datetime64[ns]` naive（交易所本地时区）；配置文件里 ISO 字符串 `2015-01-01`。
- 价格单位元、成交量单位股、成交额单位元、市值单位元；百分比字段一律小数（0.05 = 5%），列名后缀 `_pct` 的除外（明确百分点）。

## 金融正确性（红线，review 逐项核对）

1. **无未来函数**：指标在 t 日的值只依赖 ≤t 的数据；warmup 期输出 NaN 而不是偷看。
2. **T+1 入场**：t 日信号 → t+1 开盘成交；禁止用 t 日收盘价当成交价。
3. **可成交性**：入场日停牌/一字涨停剔除样本；卖出日跌停锁死顺延（Tier3）。
4. **Point-in-time universe**：用 instruments 的上市/退市区间，禁止拿"今天还活着的股票列表"回测历史。
5. **费用**：Tier2/3 必须含 `costs.py` 的费用；Tier1 报告需注明未含费用。
6. **除权处理**：研究一律用复权价；原始价只用于涨跌停/成交judgment。

## 测试

- `tests/unit/`：无 IO（除 `tests/fixtures/`）、无网络、毫秒级；CI 运行。
- `tests/integration/`：`@pytest.mark.integration`，需要 `DATA_ROOT` 真实数据，审查者本地运行。
- 黄金值测试：TDX 函数与指标必须有 fixture 黄金 CSV 对照（生成方法记录在 `tests/fixtures/README.md`）；容差用 `rtol=1e-10`（同算法）或卡中指定值（跨实现）。
- fixture ≤200KB/文件；真实小样本（几只股票几年）优于合成数据，除非测边界。

## Git

见 `docs/workflow.md` §Git 约定。补充：`.env`、`backtest_results/`、`exports/pine/*.pine`（示例除外）、`DATA_ROOT` 一律不进 git。

## 文档

- 代码行为变更必须同步更新对应 `docs/*.md`（审查项）。
- 决策变更走 ADR（`docs/decisions/ADR-TEMPLATE.md`），不改历史 ADR，只新增并标注 supersedes。

# dashboard.md — 可视化看板与 Pine 导出规范

> 对应 ADR-0003。任务卡：TASK-040~043（M4）。

## 1. 形态

本地 FastAPI 服务（`myquant dash`，默认 `127.0.0.1:8501`）+ 纯静态前端，图表用 **TradingView Lightweight Charts**（官方开源，Apache-2.0）。不依赖外网（vendor 本地化）。

## 2. JSON API 契约（TASK-040）

所有时间戳为 Unix 秒（LWC 惯例）；价格默认 qfq 复权（`adjust` 参数可选 raw/qfq/hfq）。

```
GET /api/symbols?q=平安&universe=nostar
  → [{"symbol":"sz000001","name":"平安银行","exchange":"sz"}]

GET /api/ohlcv?symbol=sz000001&start=2023-01-01&end=2024-12-31&adjust=qfq
  → {"symbol":"sz000001","adjust":"qfq",
     "bars":[{"time":1672531200,"open":..,"high":..,"low":..,"close":..,"volume":..}, ...]}

GET /api/indicator?symbol=sz000001&name=dual_trend&params={"n1":10}
  → {"name":"dual_trend",
     "lines":{"white":[{"time":..,"value":..},...],"yellow":[...]},
     "panes":{"j":[...]}}                       # lines=主图叠加, panes=副图

GET /api/signals?symbol=sz000001&name=b1_v242_62&start=...
  → {"name":"b1_v242_62",
     "markers":[{"time":..,"position":"belowBar","shape":"arrowUp","text":"B1"}]}

GET /api/runs                     → 已完成研究/回测 run 列表（读 backtest_results/ 与 mlruns）
GET /api/runs/{run_id}            → {"equity":[{"time":..,"value":..}],"trades":[...],"stats":{...}}
```

指标/信号名即 `quant.signals.registry` 的注册名——前端不写死任何指标逻辑。

## 3. 前端（TASK-041/042）

- `static/index.html + app.js`：符号搜索框、K线主图（蜡烛+成交量）、指标叠加选择器、信号 marker 开关、run 选择器（权益曲线副图 + 交易标记）。
- **Lightweight Charts 注意**：使用 v5.x，series markers 走 `createSeriesMarkers(series, markers)`（v4 的 `series.setMarkers` 已移除）。
- **Vendoring**：`static/vendor/lightweight-charts.standalone.production.js` 钉版提交，同目录保留 LICENSE 与 NOTICE；页脚可见处标注 "Charting by TradingView Lightweight Charts™" 并链接 https://www.tradingview.com/ （许可要求的署名）。

## 4. Pine Script 导出（TASK-043）

- `myquant pine export kdj dual_trend b1_v242_62 --out exports/pine/`
- 生成 Pine **v6** indicator 源码，人工粘贴到 TradingView（网页/桌面）。
- 已知不可精确移植项（写入每个 .pine 头注释）：
  - `AMOUNT`（成交额）Pine 无内置 → 用 `hlc3*volume` 近似（活跃市值指标受影响，仅形态参考）；
  - `CAPITAL`（流通股本）无 → 市值过滤条件导出时降级为注释；
  - `INBLOCK`（板块）无 → 板块剔除降级为注释；
  - TDX `SMA(X,N,M)` 在 Pine 中以 `ta.rma` 风格自定义函数实现：`s := (m*x + (n-m)*nz(s[1], x)) / n`。
- **验收口径**：同一符号同一区间，Pine 图上信号出现的日期与本地 dashboard 的 marker 日期抽样一致（允许因数据源差异有 ±1 根 K 线出入，需记录）。

## 5. 社区 TradingView MCP（可选，后期）

只读方向（拉 TradingView 行情/TA 到对话）或控制 TradingView Desktop 的社区 MCP 存在，但不能把自有回测信号画上 TradingView 图表；不纳入 M4 范围，如需求出现再立 ADR。

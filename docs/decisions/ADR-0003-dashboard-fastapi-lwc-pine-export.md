# ADR-0003: 可视化 = FastAPI + Lightweight Charts 自建看板，辅以 Pine Script 导出

- 状态：accepted
- 日期：2026-07-06
- 决策人：用户（选择"自建 Dashboard + Pine 导出"）+ 规划者

## Context

用户希望用 TradingView 呈现策略与量化结果。事实核查（2026-07）：TradingView **无官方 API** 可推送自有数据/信号到其托管图表；社区 MCP 仅支持读取行情/TA 或控制 TradingView Desktop，无法叠加自有回测结果。TradingView 官方开源的 Lightweight Charts（Apache-2.0，要求可见署名）可自建同观感图表并完全掌控叠加内容。

## Decision

- 主体：本地 FastAPI + Lightweight Charts 看板（`myquant dash`），从 qlib/staging 读数，K线上叠加指标线、信号 marker、回测权益与交易（契约见 dashboard.md）。
- 辅助：Pine Script v6 导出器，把指标翻译后粘贴到真实 TradingView 供人工盯盘（已知降级项：AMOUNT/CAPITAL/INBLOCK 不可移植，见 dashboard.md §4）。
- 社区 TradingView MCP 不纳入范围，需求出现再立新 ADR。

## Consequences

- 得到：完全可控的策略可视化 + 真实 TradingView 上的人工盯盘补充。
- 放弃：在 TradingView 官方平台内直接展示回测结果（技术上不可行）。
- 风险：前端维护成本（缓解：纯静态 + vendor 钉版，无构建链）；LWC v5 API 变更（markers 走 createSeriesMarkers）。

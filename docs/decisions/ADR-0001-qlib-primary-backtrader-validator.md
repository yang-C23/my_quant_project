# ADR-0001: qlib 为主研究/回测引擎，Backtrader 降级为交易级验证器

- 状态：accepted
- 日期：2026-07-06
- 决策人：用户（经选项确认）+ 规划者

## Context

用户要求以成熟、稳定、持续维护的开源量化平台为核心，路线为：指标验证 → 因子化 → 因子模型 → ML，硬件 9900X + RTX 5090。v1 使用 Backtrader（上游已停止维护），且被误用为前向收益评估器（事件循环跑全市场，小时级耗时）。qlib（Microsoft）截至 2026 年仍活跃维护，原生支持 A股（cn region）、1min 数据、Alpha 因子库、LightGBM/torch 建模与组合回测；用户笔记中的原始设想即 "Backtrader + Qlib"。

## Decision

- qlib 承担：因子研究、IC/分层、组合级回测（TopkDropout 等）、后期 ML（M6）。
- Backtrader 保留唯一职责：交易级验证（T+1、涨跌停锁死、停牌、费用滑点下复核候选策略），复用 v1 已验证的约束逻辑。
- 前向收益评估从 Backtrader 迁出，改为向量化事件研究（Tier1，见 backtest_platform.md）。

## Consequences

- 得到：成熟因子/ML 生态、A股原生支持、研究吞吐提升 1~2 个数量级、GPU 可用。
- 放弃：单引擎的简单性；需维护 qlib→backtrader 的数据桥（bt_feed）。
- 风险：qlib 与 numpy2/pandas2 的兼容性（缓解：M0 冒烟测试 + 独立 conda env 回退阶梯，见 TASK-001）。

## Alternatives considered

- 纯 qlib：丢弃已验证的 A股微观约束实现，交易级细节要在 qlib executor 重写，前期成本高。
- Backtrader + vectorbt：短期最快，但因子模型/ML 工作流需完全自建，与长期路线冲突。

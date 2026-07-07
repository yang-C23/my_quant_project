# TASK-061 Findings（审查者修订版）

IS window: 2015-01-01 to 2021-12-31。样本 = 指数 sh999999（不受采样问题影响）。
审查者修订内容：sell_th 网格扩展至 −1.0/−0.5（首轮 top-5 全落在 −1.5 边界），并按
PLAN.md 预声明判据重新裁定候选。

Reproduce:

```bash
myquant research configs/research/amv.yaml
```

## K 系数

K 从 1.8 → 2.6 仅等比缩放 AMV OHLC，`amv_pct` 最大漂移 5.15e-14 ≈ 浮点噪声。
**K 不是择时优化维度**，保留 2.13 仅为视觉刻度延续。（Codex 原结论，复核通过。）

## 变体级结论（全网格 8×9×4 组合中位数）

| variant | median cumulative |
|:---|---:|
| confirm_life | 0.600 |
| confirm_2d | 0.371 |
| confirm_break | 0.358 |
| immediate | 0.272 |

confirm_life（买入需 amv_close > 生命线确认）对 immediate 呈**变体级压制**——不依赖任何
具体阈值选择，是右侧确认逻辑有效性的最强 IS 证据。

## 网格边界修复后的形状

扩展后 sell_th 在 **−1.0 处出现内部极值**（−0.5 回落），不再是边界解；confirm_life 在
buy 2.5–4.5 × sell −1.0 是一条平台（cum 1.39–1.55）。但按预声明邻域判据
（±1 步全邻居 ≥70% 峰值且中位数>基线），sell=−1.5 翼侧（cum ~0.9–1.0，约峰值 60%）
不达标 → **调参最优点判为悬崖翼平台，不予录取**。判据从严，不放宽。

## 候选（进入 OOS，≤2 组）

```json
[
  {"k": 2.13, "buy_th": 4.0, "sell_th": -2.3, "variant": "confirm_life", "note": "structural: z哥原版阈值不动，仅加生命线右侧确认；由变体级中位数压制入选，非参数搜索产物"}
]
```

| | cumulative | annual | max_dd | waves | win | PF | switches/yr |
|:---|---:|---:|---:|---:|---:|---:|---:|
| baseline（z哥原版 immediate） | 0.310 | 0.039 | −0.335 | 47 | 0.447 | 1.493 | 13.4 |
| candidate（confirm_life） | 0.595 | 0.069 | −0.189 | 37 | 0.432 | 2.210 | 10.6 |

胜率略降（0.447→0.432）但单波质量和回撤大幅改善、切换更少——典型右侧交易画像：
放弃左侧最低点，换取确认后的高质量波段。

## 右侧代价（原版阈值，Codex 原表复核通过）

confirm_life 相对 immediate：47 个入场确认掉 10 个（其中 8 个是 immediate 亏损波段=
避免的假信号），确认延迟平均少赚 0.33%。

## 局限

- Tier1 无费用：候选 switches/yr ≈ 10.6，按指数 ETF 单边 ~5bp 估算年拖累 ~0.1%，
  对年化 6.9% 不构成翻转风险；Tier3（M3 后）复核。
- 单指数单段历史，OOS 2022–2024 是唯一裁决（TASK-066，审查者执行）。

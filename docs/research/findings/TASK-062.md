# TASK-062 Findings（审查者修订版）

IS window: 2015-01-01 to 2021-12-31。样本 = 800 只 `stocks_nostar` 种子化随机抽样
（seed=42，warmup 275 天）。首轮"first 300 symbols"全为北交所股（F-1），结论作废；
n_shape 经审查者向量化（F-6）后重跑。本版以重跑结果为准。

Reproduce:

```bash
myquant research configs/research/b1.yaml
```

## 基线（z哥原版 b1_v242_62 / j_max=13 / 阈值不动）

| signals | signals/year | h5 avg | h5 win | h5 PF | density_ok |
|---:|---:|---:|---:|---:|:---|
| 3568 | 509.7 | **−0.00078** | 0.4335 | **0.9711** | yes |

真实样本下 B1 原版作为独立入场信号**费前即为负期望**。首轮 300 北交所样本报出的
"信号稀疏"（12/年）是废样本假象——真实密度约 510/年，密度门槛全网格轻松通过。

## 全网格结论（26 case）

- **25/26 行 PF < 1.0**：j_max 放宽、line_mult、plry_mult、three_sum_min、yangyin_scale
  任何单维调整都无法把 h5 均值拉回正值；三 preset（_62/b/p）之间无本质分化。
- **唯一正收益行 = `condition=dual_zone`**（B1 ∩ 双线多头区间）：
  2253 信号（322/年）、h5 avg **+0.00186**、win 0.4531、PF **1.0727**、
  regime0 +0.32% / regime1 +0.06%（牛市贡献为主）。
- `n_shape` / `breath_active` 组合条件均无法翻正（PF 0.95–0.99）。

## 结论与候选

dual_zone 行不立为候选：① case 网格的 stable_neighborhood 列不可采信（F-5，
人工列表无邻域语义）；② h5 笔均 +0.19%（费前）对 ~0.15–0.3% 双边成本无生存空间；
③ 该行是全网格 26 选 1 的极值，无邻域佐证，过拟合风险高。

```json
[]
```

**无候选进入 OOS。** B1 按 Tier1 证据不具备独立入场信号价值。唯一有信息量的方向
（留档，非候选）：**B1 的边际全部来自与双线趋势区间的交集**——与 TASK-063
"golden_cross 入场费前 PF 1.15"互为印证，即 B1 本身不选股、趋势区间才选时。
若未来复用 B1，方向是作为双线体系内的入场时点过滤器，用结构化网格重验，
而非独立策略。

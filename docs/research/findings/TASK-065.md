# TASK-065 Findings（审查者修订版）

IS window: 2015-01-01 to 2021-12-31。样本 = 800 只 `stocks_nostar` 种子化随机抽样
（seed=42）。首轮"前 300 符号"样本全为北交所股、且 turnover 字段未加载，两处经审查者
修复后重跑（见 docs/reviews/R1-batch1-review.md F-1/F-3/F-4）；修复后日均截面 ~465 只
（首轮仅 ~50），turnover 因子真实计算（首轮 mean_n=0 为假阴性）。

Reproduce:

```bash
myquant research configs/research/exploratory.yaml
```

判定规则（预声明）：`|ICIR| >= 0.3` 且分层 |Spearman| >= 0.8（负向单调=反向可交易）。

## 结果

| factor | params | IC mean | ICIR | mean n | q Spearman | top h5 avg | top h5 PF | decision |
|:---|:---|---:|---:|---:|---:|---:|---:|:---|
| washout_area_ratio | w20 | 0.0205 | 0.195 | 468 | 0.7 | 0.0041 | 1.173 | invalid_or_uncertain |
| washout_area_ratio | w40 | 0.0230 | 0.221 | 467 | 1.0 | 0.0045 | 1.191 | invalid_or_uncertain |
| washout_area_ratio | w60 | 0.0252 | 0.257 | 465 | 1.0 | 0.0041 | 1.177 | invalid_or_uncertain |
| red_green_vol_ratio | w14 | −0.0160 | −0.151 | 468 | −0.4 | 0.0028 | 1.103 | invalid_or_uncertain |
| red_green_vol_ratio | w28 | −0.0222 | −0.211 | 467 | −0.9 | 0.0026 | 1.092 | invalid_or_uncertain |
| red_green_vol_ratio | w57 | −0.0241 | −0.244 | 465 | −0.9 | 0.0010 | 1.036 | invalid_or_uncertain |
| bottom_area_score | w60/p120 | −0.0053 | −0.031 | 164 | −0.7 | 0.0054 | 1.265 | invalid_or_uncertain |
| turnover_weighted_cost | w30 | −0.0439 | −0.254 | 417 | −0.7 | 0.0006 | 1.018 | invalid_or_uncertain |
| turnover_weighted_cost | w60 | −0.0483 | −0.257 | 394 | −1.0 | −0.0010 | 0.967 | invalid_or_uncertain |
| chip_concentration | w60 | −0.0242 | −0.122 | 416 | 0.8 | 0.0013 | 1.041 | invalid_or_uncertain |

## 2026-07 协议修复后复跑

复跑命令：`myquant research configs/research/exploratory.yaml`（real 720.27s）。`top_h5`
事件研究改为 ashare 入场过滤后，top-event 数值小幅变化；IC/分层判定未变，所有因子仍为
`invalid_or_uncertain`，结论方向未翻转。

| factor | params | top_h5 avg old/new | top_h5 PF old/new | decision new |
|:---|:---|---:|---:|:---|
| washout_area_ratio | w20 | 0.0041 / 0.0040 | 1.173 / 1.170 | invalid_or_uncertain |
| washout_area_ratio | w40 | 0.0045 / 0.0044 | 1.191 / 1.188 | invalid_or_uncertain |
| washout_area_ratio | w60 | 0.0041 / 0.0040 | 1.177 / 1.173 | invalid_or_uncertain |
| red_green_vol_ratio | w14 | 0.0028 / 0.0028 | 1.103 / 1.103 | invalid_or_uncertain |
| red_green_vol_ratio | w28 | 0.0026 / 0.0026 | 1.092 / 1.092 | invalid_or_uncertain |
| red_green_vol_ratio | w57 | 0.0010 / 0.0010 | 1.036 / 1.033 | invalid_or_uncertain |
| bottom_area_score | w60/p120 | 0.0054 / 0.0054 | 1.265 / 1.263 | invalid_or_uncertain |
| turnover_weighted_cost | w30 | 0.0006 / 0.0006 | 1.018 / 1.018 | invalid_or_uncertain |
| turnover_weighted_cost | w60 | -0.0010 / -0.0010 | 0.967 / 0.969 | invalid_or_uncertain |
| chip_concentration | w60 | 0.0013 / 0.0014 | 1.041 / 1.042 | invalid_or_uncertain |

## 结论

**没有因子达到预声明有效性门槛，本卡不产生任何 R1 优化卡。**

值得留档的两个"最接近"家族（|ICIR| ≈ 0.25，都差 ~0.05）：

1. `washout_area_ratio`（洗盘面积比，窗口越长越强，w40/w60 分层完美正向单调）——
   z哥"底部红绿量占比"直觉在截面上方向正确但强度不足以单独成立；
2. `turnover_weighted_cost`（价格相对换手加权成本，负向：偏离成本越高未来收益越低，
   w60 分层完美负向单调）——均值回归型筹码代理。

两者留作 M6 因子模型的复合因子备选（多因子组合下 |ICIR|~0.25 的因子仍有贡献价值），
不在 R1 内继续单因子调参。

Candidate params JSON:

```json
[]
```

## 2026-07-09 审查者注（TASK-070 universe 净化后复跑）

净化样本复跑：全部因子 decision 仍为 invalid_or_uncertain。**留档理由勘误**：washout_area_ratio
的"完美正单调"不复现（w40 分位 Spearman 1.0→0.1、w60 ICIR 0.257→0.222），单调性对样本构成敏感，
M6 复启时仅按普通弱正 IC 因子对待；turnover_weighted_cost 负单调保持（Spearman −0.9/−1.0），
留档理由不变。详见 R1-final-report 勘误 2。

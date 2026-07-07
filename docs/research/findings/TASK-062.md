# TASK-062 Findings

IS window: 2015-01-01 to 2021-12-31. Research sample: first 300 `stocks_nostar` symbols with 275 warmup days.

Reproduce:

```bash
myquant research configs/research/b1.yaml
```

Three preset baselines:

| preset | signals/year | h5 avg | h5 win | h5 profit_factor | density_ok |
|:---|---:|---:|---:|---:|:---|
| b1_v242_62 | 12.4274 | -0.031838 | 0.310345 | 0.286499 | no |
| b1_v242b | 17.7126 | -0.008815 | 0.379032 | 0.753082 | no |
| b1_v242p | 1.9998 | 0.002238 | 0.500000 | 1.091920 | no |

Single-dimension readout in this sample:

| dimension | IS observation |
|:---|:---|
| preset | `b1_v242p` improves h5 profit_factor but has only 14 h5 events. |
| j_max | Looser `j_max` increases events but keeps h5 avg negative. |
| line_mult | Lower `line_mult` adds events; no positive dense row. |
| plry_mult | Raising/lowering PLRY multiplier did not produce a positive dense row. |
| three_sum_min | Stricter values reduced density without improving h5 avg. |
| yangyin_scale | A looser scale raised density but h5 avg stayed negative. |
| combination filters | `n_shape`, `breath_active`, and `dual_zone` did not rescue the best dense rows. |

Top IS rows:

| case | signals/year | h5 avg | h5 win | h5 profit_factor | stable |
|:---|---:|---:|---:|---:|:---|
| b1_v242p / j13 / line0.985 / none | 1.9998 | 0.002238 | 0.500000 | 1.091920 | no |
| b1_v242b / j13 / line0.985 / none | 17.7126 | -0.008815 | 0.379032 | 0.753082 | no |
| b1_v242_62 / j20 / line0.985 / plry2.15 / three3 / yscale1.2 / breath_active | 5.9994 | -0.014255 | 0.428571 | 0.570695 | no |
| b1_v242p / j20 / line0.995 / n_shape | 3.7139 | -0.014030 | 0.423077 | 0.546525 | no |
| b1_v242p / j20 / line0.995 / breath_active | 3.7139 | -0.014030 | 0.423077 | 0.546525 | no |

Best density-qualified row:

| case | signals/year | h5 avg | h5 win | h5 profit_factor |
|:---|---:|---:|---:|---:|
| b1_v242_62 / j20 / line0.985 / plry1.75 / three2 / yscale0.8 / n_shape | 34.2824 | -0.020552 | 0.343096 | 0.480679 |

Candidate params JSON:

```json
[]
```

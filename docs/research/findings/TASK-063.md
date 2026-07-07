# TASK-063 Findings

IS window: 2015-01-01 to 2021-12-31. Research sample: first 300 `stocks_nostar` symbols with 220 warmup days.

Reproduce:

```bash
myquant research configs/research/dual_trend.yaml
```

Pair matrix:

| entry | exit | trades | win | avg | median | profit_factor | hold | MAE | MFE |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| golden_cross | dead_cross | 84 | 0.404762 | 0.131021 | -0.016851 | 3.54949 | 58.6786 | -0.092329 | 0.385859 |
| golden_cross | close_lt_white_2d | 85 | 0.482353 | 0.002236 | -0.004065 | 1.07510 | 19.5294 | -0.052497 | 0.101593 |
| golden_cross | close_lt_yellow | 85 | 0.364706 | 0.028876 | -0.023342 | 1.71099 | 29.6824 | -0.059478 | 0.181769 |
| golden_cross | stop_8 | 70 | 0.385714 | 0.093444 | -0.065351 | 2.57713 | 54.7571 | -0.080623 | 0.326292 |
| golden_cross | dead_cross_stop_8 | 84 | 0.285714 | 0.062268 | -0.046360 | 2.25017 | 44.9643 | -0.069874 | 0.272832 |
| dual_entry | dead_cross | 97 | 0.402062 | 0.134086 | -0.057692 | 3.09336 | 44.9897 | -0.114988 | 0.374348 |
| dual_entry | close_lt_white_2d | 262 | 0.339695 | -0.004780 | -0.006391 | 0.665678 | 2.1031 | -0.025910 | 0.030561 |
| dual_entry | close_lt_yellow | 151 | 0.192053 | 0.023548 | -0.029885 | 1.60942 | 12.3510 | -0.055274 | 0.133237 |
| dual_entry | stop_8 | 112 | 0.250000 | 0.105180 | -0.075284 | 2.58527 | 34.3661 | -0.088536 | 0.299975 |
| dual_entry | dead_cross_stop_8 | 114 | 0.280702 | 0.086884 | -0.071353 | 2.46449 | 30.8509 | -0.081544 | 0.274476 |

Fake golden-cross rate: 86 golden crosses; dead cross within 5 bars = 0.046512.

Interpretation: dead-cross exits dominate average return and profit_factor, but both candidate rows have negative median trade return. This is a low-hit-rate, high-right-tail profile.

Candidate params JSON:

```json
[
  {"entry": "golden_cross", "exit": "dead_cross", "max_hold": 120},
  {"entry": "dual_entry", "exit": "dead_cross", "max_hold": 120}
]
```

# TASK-064 Findings

IS window: 2015-01-01 to 2021-12-31. Research sample: first 300 `stocks_nostar` symbols with 180 warmup days.

Reproduce:

```bash
myquant research configs/research/shortterm.yaml
```

Top IS rows:

| entry | hold | stop | trades | win | avg | median | profit_factor | MAE | MFE |
|:---|---:|:---|---:|---:|---:|---:|---:|---:|---:|
| single_needle_proxy | 4 | 0.03 | 45 | 0.488889 | 0.045300 | 0.000000 | 3.58659 | -0.033342 | 0.101842 |
| single_needle_proxy | 3 | 0.03 | 45 | 0.533333 | 0.038105 | 0.008197 | 3.38326 | -0.031723 | 0.073131 |
| brick_relaxed_smallup_0.02 | 6 | 0.02 | 88 | 0.329545 | 0.015771 | -0.006329 | 2.37443 | -0.019873 | 0.045725 |
| brick_len_smallup_0.04 | 6 | none | 60 | 0.416667 | 0.021533 | -0.008389 | 2.31279 | -0.028607 | 0.068119 |

Single-needle prior check:

| hold | stop | trades | win | win CI | profit_factor | PF CI |
|---:|:---|---:|---:|:---|---:|:---|
| 4 | 0.03 | 45 | 0.488889 | [0.355000, 0.622222] | 3.58659 | [1.33495, 8.05786] |

The proxy beats the note prior point estimate for win rate and payoff in this sample, but the CI is wide because there are only 45 trades.

GEM excluded check for top-2 rows was unchanged in this sample slice.

Candidate params JSON:

```json
[
  {"entry": "single_needle_proxy", "max_hold": 4, "stop": 0.03, "two_day_no_profit": true},
  {"entry": "single_needle_proxy", "max_hold": 3, "stop": 0.03, "two_day_no_profit": true}
]
```

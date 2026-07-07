# TASK-060 Findings

IS window: 2015-01-01 to 2021-12-31.

Reproduce:

```bash
myquant research configs/research/_TEMPLATE.yaml
```

Template demo: 10-stock `kdj_oversold` scan, 5 parameter groups, completed in under 3 minutes.

Top IS rows:

| j_threshold | signals/year | h5 avg | h5 profit_factor | RankIC h5 | stable |
|---:|---:|---:|---:|---:|:---|
| 0 | 13.1416 | 0.035078 | 2.75795 | -0.139163 | yes |
| 5 | 24.2833 | 0.031191 | 2.20258 | -0.114340 | yes |
| 13 | 37.1392 | 0.021955 | 1.87743 | -0.241986 | yes |

Candidate params JSON:

```json
[]
```

# TASK-061 Findings

IS window: 2015-01-01 to 2021-12-31.

Reproduce:

```bash
myquant research configs/research/amv.yaml
```

K check: changing K from 1.8 to 2.6 only rescales AMV OHLC. `amv_pct` max absolute drift versus K=1.8 was `5.15143e-14`, so K is not a timing optimization dimension. Baseline K=2.13 is retained for visual scale continuity.

Baseline original parameters:

| buy_th | sell_th | variant | cumulative | max_dd | waves | win | profit_factor |
|---:|---:|:---|---:|---:|---:|---:|---:|
| 4.0 | -2.3 | immediate | 0.309691 | -0.334968 | 47 | 0.446809 | 1.492836 |

Top IS rows:

| buy_th | sell_th | variant | cumulative | max_dd | waves | win | profit_factor | stable |
|---:|---:|:---|---:|---:|---:|---:|---:|:---|
| 4.5 | -1.5 | confirm_life | 1.204613 | -0.118425 | 42 | 0.547619 | 4.780049 | no |
| 3.0 | -1.5 | confirm_life | 1.073282 | -0.120641 | 55 | 0.490909 | 3.061109 | no |
| 5.0 | -1.5 | confirm_life | 1.022992 | -0.118425 | 41 | 0.560976 | 4.499806 | no |
| 4.0 | -1.5 | confirm_life | 1.019219 | -0.121598 | 47 | 0.553191 | 3.280740 | no |
| 3.5 | -1.5 | confirm_life | 0.968295 | -0.121598 | 52 | 0.500000 | 2.973863 | no |

Variant median cumulative return:

| variant | median cumulative | median waves | median win | median profit_factor |
|:---|---:|---:|---:|---:|
| confirm_life | 0.478542 | 30.5 | 0.468627 | 2.304407 |
| confirm_break | 0.300349 | 29.5 | 0.428571 | 1.808672 |
| confirm_2d | 0.282321 | 31.0 | 0.453463 | 1.670316 |
| immediate | 0.183865 | 40.5 | 0.440930 | 1.352448 |

Right-side cost at original thresholds:

| variant | base entries | confirmed | missed avg | avoided false | win delta |
|:---|---:|---:|---:|---:|---:|
| confirm_life | 47 | 37 | 0.003311 | 8 | -0.014376 |
| confirm_2d | 47 | 34 | 0.009368 | 11 | -0.005632 |
| confirm_break | 47 | 35 | 0.007073 | 8 | -0.018237 |

Candidate params JSON:

```json
[]
```

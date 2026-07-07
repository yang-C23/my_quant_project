# TASK-065 Findings

IS window: 2015-01-01 to 2021-12-31. Research sample: first 300 `stocks_nostar` symbols.

Reproduce:

```bash
myquant research configs/research/exploratory.yaml
```

Decision rule: effective only if `|ICIR| >= 0.3` and quantile Spearman >= 0.8.

Results:

| factor | params | IC mean | ICIR | mean n | q Spearman | top h5 avg | top h5 PF | decision |
|:---|:---|---:|---:|---:|---:|---:|---:|:---|
| washout_area_ratio | window 20 | 0.002143 | 0.013135 | 51.2875 | -0.3 | 0.011560 | 1.48848 | invalid_or_uncertain |
| washout_area_ratio | window 40 | -0.009846 | -0.049541 | 49.2704 | -0.9 | 0.009193 | 1.37122 | invalid_or_uncertain |
| washout_area_ratio | window 60 | -0.002989 | -0.015162 | 47.6864 | -0.6 | 0.010950 | 1.45618 | invalid_or_uncertain |
| red_green_vol_ratio | window 14 | 0.004891 | 0.029539 | 51.7928 | 0.6 | 0.012533 | 1.50849 | invalid_or_uncertain |
| red_green_vol_ratio | window 28 | 0.000352 | 0.001966 | 50.3636 | 0.9 | 0.014865 | 1.60775 | invalid_or_uncertain |
| red_green_vol_ratio | window 57 | 0.001453 | 0.007373 | 47.9276 | 0.7 | 0.018339 | 1.72661 | invalid_or_uncertain |
| bottom_area_score | window 60 / price 120 | -0.001575 | -0.002670 | 8.3283 | 0.6 | 0.035041 | 2.89296 | invalid_or_uncertain |
| turnover_weighted_cost | window 30 | NaN | NaN | 0 | NaN | NaN | NaN | invalid_or_uncertain |
| turnover_weighted_cost | window 60 | NaN | NaN | 0 | NaN | NaN | NaN | invalid_or_uncertain |
| chip_concentration | window 60 | -0.019343 | -0.071805 | 47.3275 | 1.0 | 0.015799 | 1.50959 | invalid_or_uncertain |

Conclusion: no factor meets the predeclared effectiveness threshold. `bottom_area_score` and `chip_concentration` show event-study averages worth remembering, but ICIR is far below threshold, so no optimization card should be opened from this sample.

Candidate params JSON:

```json
[]
```

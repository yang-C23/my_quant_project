# docs/parity/ — v1 黄金参照报告（换引擎不换结论）

这些文件是 v1 引擎（Backtrader 前向收益评估器，代码版本 = main 分支 `f132436`）在本机真实数据上产出的报告快照，**固化提交**作为 v2 的 parity 基准。原始文件在 gitignored 的 `backtest_results/`。

| 文件 | 来源 run | 口径 | 用途 |
|---|---|---|---|
| `kdj_j0_20260311_222907_summary.{csv,md}` | `run_backtest.py` 默认 5 只样本股（sh600036/sh600519/sh601318/sz000001/sz000858） | KDJ J<0（前一bar J），2015-01-01~2024-12-31，horizons 1/3/5，次日开盘入场 | TASK-025 小样本对拍（第一道） |
| `pipeline_kdj_forward_return_20260311_225334_summary.csv` | `run_pipeline.py configs/pipeline_kdj_j0.yaml`，全市场（exclude_boards=[star]，~5800 符号，113.7 万信号） | 同上 | **M2 gate**：TASK-025 全市场 parity |
| `dualtrend_breath_full_20260710_124211_summary.csv` | 审查者 2026-07-10 用 v1 原码（main 分支）× 冻结 PG（数据止 2026-03-11）重生成：`run_dualtrend_breath_backtest.py --symbols <v2 canonical universe 5466 只> --start 2015-01-01 --end 2026-03-11` | DualTrend 呼吸策略（J13/VR3.5 等默认参）；黄金总体=5305 只存活符号（160 只窗口内数据不足、1 只 sz000937 v1 RSV 除零被 engine try/except 跳过——跳过语义即 v1 语义） | **M3 gate**：TASK-032 交易级 parity（现行对照目标） |
| `dualtrend_breath_full_20260224_220316_summary.csv` | v1 2026-02-24 原始运行（窗口/总体参数未留档） | 同上 | **已废弃留档**：生成后 PG 又更新至 2026-03-11（其间 223 条除权→v_qfq 全历史重算+舍入），经审查者证实在冻结快照上连 v1 自身都不可复现（TASK-032-review.md） |

判定标准见 `docs/backtest_platform.md` §5：样本数完全一致、胜率 ±0.1pp、均值 ±5bps。

已知观察（先记录，parity 时注意）：全市场报告 horizon=1 的 `avg_return≈9.7%` 而 median≈0.04%——极端右偏，疑为低价股/数据异常离群点主导。**parity 只要求复现，不要求认同**；复现成功后应另开研究卡审计离群样本（进 M6 backlog）。

# TASK-013 Review（第 1 轮）

- 日期：2026-07-07　|　审查者：Claude (Fable 5)　|　分支：`task/TASK-013-qlib-dump`（28aa02b，堆叠于 012）

## 验收（审查者独立运行）

| # | 检查 | 结果 |
|---|---|---|
| 1 | `pytest tests/unit/test_qlib_dump.py`（2）+ 全套 68 + ruff | PASS |
| 2 | 集成：`myquant dump cn-daily` 全量 29.34M 行 / 12,169 instruments / 16 字段 / **2m18s**（预算 5min） | PASS |
| 3 | `qlib.init` + `D.features` 三符号全历史对齐 PG：$factor 逐位相等；hfq 价 **max_rel 5.8e-8**（float32 精度界内，达标 1e-6） | PASS |
| 4 | instruments：all=12169 / nostar=11561 / nostar 内 688-689 = 0；退市股可读（区间截断） | PASS |

## 关键发现（写入 TASK-016 验证口径）

初测 `$close` vs PG `v_hfq_daily` 出现 1e-4~4e-4 "超差"，定位为 **PG 视图对 hfq 价保留两位小数的显示舍入**（低价区相对误差放大），非数据错误。**TASK-016 的 C5 检查必须用 `daily_kline.close × adjust_factor.hfq_factor` 重算对齐，不得用视图值**；对视图只做 |Δ|≤0.005 绝对带。

## 质量意见

- vendor 单文件（`_qlib_dump_vendor.py`）注明 qlib 0.9.7 FileFeatureStorage 格式来源——安装包确实不含 dump_bin.py，处置合理。
- flags outer-merge 使停牌日以 NaN 价 + suspended=1 形式进 bin（29.34M > 28.67M 的来源），符合 qlib 日历对齐语义。
- 非阻塞：dump 过程有一条 pandas FutureWarning（`fillna(False)` on object 列，`bool_feature` 处）——下一张触碰该文件的卡顺手清理。

**PASS** —— 已合并。

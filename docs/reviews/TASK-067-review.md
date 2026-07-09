# TASK-067 Review — qlib 批量 IO + CLI 入口守卫

- 分支：`task/TASK-067-io-batch-cli-guard`（8cf98ab）
- 审查者：Claude（规划/审查代理）
- 日期：2026-07-09
- 结论：**PASS**（全部 AC 通过；性能 1.35–1.38× 未达 3× 目标，但符合卡面"附瓶颈分析即不算失败"条款）

## 白名单与范围

- `git diff v2...task/TASK-067-io-batch-cli-guard`：10 个文件，全部在卡面 Files-to-touch + STATUS.md 默认项内（`scripts/check_whitelist.py --base v2` 复核通过）。
- `scripts/check_no_hardcoded_paths.py`：通过（src/quant/ 无绝对路径字符串）。
- Scope 逐条对照：`get_ohlcv_batch` 签名与卡面一致；forward_returns / trade_pairs / exploratory / factors 四处调用点全部改为批量加载；`cli.py` 末尾补 `__main__` 守卫。Non-goals 未越界（optimize.py 未动、无新依赖、未碰 OOS）。

## 语义等价性审读（diff 级）

1. **qfq latest-factor**：批量 `_latest_factors` = 一次全区间 `$factor` 查询 → 按符号 dropna 取末值，与单符号 `_latest_factor`（不限窗、取最后非 NaN）语义一致。
2. **浮点逐位**：单符号路径 `prices / latest`（标量除）vs 批量 `div(latest_by_row, axis=0)`（逐行除）——同为 IEEE double 单次除法，逐位相同。raw 路径公式两侧一致。
3. **缺数据/缺 factor 符号**：批量静默剔除 ≡ 原调用方 `except ValueError: continue`；forward_returns 原先 qfq 失败即整符号跳过，批量侧 left-merge 后行为一致。
4. **join → merge**：`qfq.join(raw, how="left")`（按 date 索引）→ `qfq.merge(raw, on=["symbol","date"], how="left")`，键唯一，口径不变。
5. **遍历顺序**：由 universe 顺序改为 `groupby(sort=True)` 符号字典序；exploratory 输出经 CSV 逐位比对验证无影响（AC3）；dual_trend/shortterm 路径下游均按 (symbol,date) 排序后聚合，无顺序依赖。
6. **`_compute_one_signal/_compute_one_factor`**：IO 上移后指标计算仍逐符号，输入列集与原 `get_ohlcv` 输出一致（含 factor 列）；`workers` 参数保留签名以兼容调用方（`del workers`）。

## 验收命令复跑（审查者亲自执行）

| AC | 命令 | 结果 |
|---|---|---|
| 1 | `pytest -q tests/integration/test_data_api_real.py -m integration` | ✅ 3 passed（30 真实符号含退市股 seed=67；qfq/hfq/raw × 11 字段 `assert_frame_equal` 精确相等） |
| 2 | `time myquant research configs/research/exploratory.yaml` | ✅ 审查者独立复跑 branch=662.48s（Codex 报 648.63s，交叉吻合）；vs v2 基线 893.89s ≈ 1.35×，未达 3×；瓶颈分析：剩余热点 = IC/分层/top-event 逐因子 Python 计算（计算层，非 IO 层），符合卡面"不达标不算失败但须附瓶颈分析"条款 |
| 3 | `diff` 审查者复跑 CSV vs `exploratory_exploratory.v2-baseline-TASK-067.csv` vs Codex 输出 | ✅ **三方逐位一致** |
| 4 | `python -m quant.cli --help` / `myquant --help` | ✅ 均 exit 0，etl/dump/study/research/ic/update/validate 齐全 |
| 5 | `pytest -q -m "not integration"` + `ruff check .` | ✅ 169 passed, 3 deselected / All checks passed |

## 附注

- `ruff format --check .` 残余 5 个失败文件（r1_oos_final / amv_timing / optimize / test_amv_timing / test_optimize）均为**本卡白名单外的既有格式债**，与 TASK-069 卡面清单完全一致，不构成本卡打回理由。
- 本卡白名单内全部文件 format 通过。
- 性能未达 3× 的后续处理：热点在计算层而非 IO 层，已超出本卡 Scope（"只改 IO 方式"）；是否开向量化卡由规划者在 M6 研究复启时按需决定，不阻塞 M3。

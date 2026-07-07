# TASK-012 Review（第 1 轮）

- 日期：2026-07-07　|　审查者：Claude (Fable 5)　|　分支：`task/TASK-012-adjust`（690e864）

## 验收（审查者独立运行）

| # | 检查 | 结果 |
|---|---|---|
| 1 | `pytest tests/unit/test_adjust.py test_basics.py`（9）+ 全套 66 + ruff | PASS |
| 2 | 手工除权用例 + PG fixture（sz000001 全历史 8326 行，rtol 1e-9） | PASS |
| 3 | 集成：全市场 derive 28.67M 行 **1m51s**（预算 3min）；flags 实体化 18.64M 行 43s | PASS |
| 4 | **PG 黄金抽查（审查者加测）**：sh600000/sz000002/sh600036/sz000858/sh601318 全历史 hfq_factor 与 PG **逐位相等（max_rel_diff=0）** | PASS |

## 质量意见

- `xdxr_events` 的 c1→fenhong/c2→peigu/c3→songzhuangu/c4→peigujia 映射、同日多事件累加、peigujia 取最后正值——**与冻结 v1 `calc_basic.py` 逐行核对一致**（含 `if c4>0` 细节）。
- `theoretical_preclose`/ratio 方向正确（实际昨收/理论昨收，hfq 向后放大）。
- 股本时间线 c3/c4×1e4 与 v1 一致；`_attach_shares` 的逐符号 merge_asof 循环可后续换 `merge_asof(by="symbol")`（性能备注，非阻塞——当前 1m51s 足够）。
- PG fixture 196KB 贴着 200KB 上限，接受（黄金参照价值充分）。

**PASS** —— 已合并。

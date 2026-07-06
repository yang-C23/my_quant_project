# TASK-004 Review（第 1 轮）

- 日期：2026-07-06　|　审查者：Claude (Fable 5)　|　分支：`task/TASK-004-dead-code`（53f72fd + a829fee）

## 验收命令重跑结果

| # | 命令 | 结果 |
|---|---|---|
| 1 | `pytest -q -m "not integration"` + `ruff check .` | PASS（2 passed / All checks passed） |
| 2 | `import quant` OK；`grep -rn "kdj_b1_analysis"` 为空 | PASS |
| 3 | 删除为独立 commit | PASS（53f72fd 纯删除+brick 精简；a829fee 单独改 README） |

## diff 审查

- 删除清单与卡面逐项一致（13 文件：损坏研究模块+runner、4 个旧 CLI、pipeline.py、USAGE_GUIDE、两个旧 config、requirements.txt）。
- `brick.py`：`BrickIndicator` 删除、`TDXSMA` 保留并加注释指向 TASK-020 黄金值用途——正确。
- `README.md` 改写为 v2 版：安装、`myquant` 命令表（标注 planned 里程碑）、docs 索引、"v1 历史见 main 分支"——符合卡面。
- 交叉引用完整性抽查：`kdj_tdx.py` 对 `brick.TDXSMA` 的 import 仍有效；无残留对已删模块的引用。

## 结论

**PASS**。

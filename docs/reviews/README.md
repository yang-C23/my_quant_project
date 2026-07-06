# docs/reviews/ — 评审记录与 gate 报告

- 每张任务卡一份 `TASK-XXX-review.md`（规划者写）；里程碑 gate 报告命名 `M?-gate-report.md`；
  M1 数据对齐报告 `M1-validate-vs-pg.md` 由 validate 脚本生成后归档于此。

## 评审文件模板

```markdown
# TASK-XXX Review（第 N 轮）
- 日期 / 审查者 / 分支 / 对照卡版本
## 验收命令重跑结果
| # | 命令 | 结果 |    ← 卡中每条 Acceptance criteria 一行，PASS/FAIL + 关键输出
## diff 审查
- 文件白名单符合性：
- 红线检查（未来函数/T+1/可成交过滤/费用；见 conventions.md）：
- 代码质量意见：
## 结论
PASS（已 --no-ff 合并 <sha>）| CHANGES_REQUESTED（修改项编号列表）
```

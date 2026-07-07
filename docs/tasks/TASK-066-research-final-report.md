# TASK-066: R1 汇总 — OOS 裁定与最终对比报告

- Milestone: R1　|　State: backlog（061–065 全部 done 后由规划者执行，不分配给开发代理）
- Branch: 直接在 v2 上（纯文档+审查者跑 OOS）　|　Depends: TASK-061..065

## Context
PLAN §2：OOS 只允许审查者跑，每指标 ≤2 候选 + 基线各一次。

## Goal
产出 `docs/reviews/R1-final-report.md`：全指标 IS/OOS 并排总表 + 采纳/不采纳裁定 + 进入 Tier3 验证队列的清单。

## Scope（审查者执行清单）
1. 对每张 061–065 findings 的候选参数：跑 `myquant research <cfg> --oos-final <params> --i-am-the-reviewer`（OOS 2022-01-01~2024-12-31），基线同跑。
2. 汇总表列：指标 / 参数组 / IS 核心指标 / OOS 核心指标 / OOS vs 基线 / 邻域稳定 / regime 稳健 / **裁定**（采纳→Tier3 队列 / 不采纳 / 需复议）。
3. 裁定规则（预先写死，防事后合理化）：采纳 = OOS 盈亏比与均值**同时**≥基线，且 OOS 未较 IS 衰减超 50%；否则不采纳。
4. 封存段（2025+）保持未触碰的声明与校验（grep 检查各 findings/配置无 2025+ 日期）。
5. 归档并打 tag `v2.0-r1`。

## Acceptance criteria
1. R1-final-report.md 完整（每候选一行，无遗漏）；所有数字有对应复现命令。
2. OOS 运行次数审计：日志/报告中每指标 ≤3 次（2 候选+1 基线）。
3. 采纳清单同步进 docs/roadmap.md 的 Tier3 验证队列（M3 后执行）。

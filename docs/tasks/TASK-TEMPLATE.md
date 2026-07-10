# TASK-XXX: <标题>

- Milestone: M?　|　State: backlog|ready|in_progress|review|changes_requested|done
- Branch: `task/TASK-XXX-<slug>`　|　Depends: TASK-YYY, …

## Context
<为什么做；链接 docs/architecture.md、ADR、指标文档的具体小节>

## Goal
<一段话，可观察的结果>

## Scope
<精确到函数签名 / CLI 契约 / 文件行为的建造清单>

## Non-goals
<明确不做的事，防scope蔓延>

## Files to touch
<白名单：**一行一个** repo 相对路径，反引号包裹；目录以 `/` 结尾表示其下皆可。
`docs/tasks/STATUS.md` 与本卡文件默认允许、无需列出。由 `scripts/check_whitelist.py` 在 CI 强制。>
- `src/quant/<...>.py`
- `tests/unit/test_<...>.py`

## Acceptance criteria
<编号列表；每条 = 一条可运行命令 + 期望结果>

## 验收如何被作弊/退化满足？
<规划者置 `ready` 前必答，逐条审上面的 Acceptance criteria：一个"错误但结果貌似合理"的实现能否骗过它？
列出每条的退化/假阴性路径并补防线。常见攻击面（对照历史返工）：
- 样本怎么选？头部/字典序截断会不会取到畸形子集（F-1：`symbols[:300]` 全北交所）；抽样是否种子化；
- 验收数据里有没有边界样本：一字涨停/停牌/退市/空表/NaN——缺了它们，恒真/假阴性会被固化成绿测（F-2 止损入场日恒真、F-3 字段未加载假阴性）；
- "逐位一致"对照的基线，是不是可能被同一 bug 污染、或经过二次舍入的视图（TASK-013：对齐用 raw×factor 重算，勿用 v_hfq）；
- 断言会不会因空输入/默认参数而恒成立。
想不清攻击面的卡不置 `ready`。>

## 数值验证类别与变形测试（数值/研究卡必填，其余写 n/a）
<预声明验证类别（ADR-0005 §9）：**Class A**=逐位一致（parity/费用/会计/黄金复现）；
**Class B**=数值等价（必须写明 atol/rtol/ULP 上限与 NaN 语义）；**Class C**=统计等价
（分布/置信区间/方向/经济结论）。类别写错的代价见 TASK-071（B 被默认成 A，返工一轮）。
列出适用的变形/对抗测试：乱序输入结果不变、universe ±1 只样本最多换 1 个、追加未来 bar
历史信号不变、因子横截面置换后 IC/分层归零、因子 ×−1 结果对称反转、成本上调净收益不得
改善、构造跌停/停牌日不得按不可成交价成交、重复信号的去重语义显式……不适用写明理由。>

## Test plan
<要新增的单测、使用/新建的 fixtures、集成检查>

## Notes / risks
<规划者已知的坑>

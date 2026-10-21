# TASK-076 Review — trade_pairs 退出语义统一（跌停/停牌约束 + MAE/MFE 顺延）

- 分支：`task/TASK-076-exit-semantics`（f314fff）
- 审查者：Claude（规划/审查代理）
- 日期：2026-07-11
- 结论：**PASS**

## 验证

| 项 | 结果 |
|---|---|
| 白名单 | ✅ 3 文件（trade_pairs.py + 测试 + STATUS 行内），check_whitelist OK |
| Scope 逐条 | ✅ `block_limit_down=True` 无条件、无 reason 分支（diff 核对）；`_next_tradable_pos` 已无 `entry_filters` 参数与死分支；`held = bars[entry_pos:exit_exec_pos]` 右开切片 + exit_price 计入 mae/mfe 两侧极值 |
| AC1 手算 | ✅ 审查者独立逐 bar 手算 a/b/c/d 全部期望值（0.20 / −0.10 / −0.20 & 0.20 / −0.30）与用例一致；用例用 raw_open/limit_down_price 真实列名且断言 exit_date > 跌停日（阻塞确实发生，防空转 ✓） |
| 红灯复核 | ✅ 审查者将分支测试文件放到 v2 旧码上：**4 failed**（两条顺延 + 两条 MAE/MFE）、11 passed；分支上 15 passed |
| AC3 | ✅ `grep entry_filters` 仅剩入场侧（run_pair_study 签名与 ashare 分支） |
| AC2 | ✅ 既有断言仅首用例 mae/mfe 语义核对（值未变，窗口右开等价）——STATUS 备注清单与 diff 一致 |
| 质量门 | ✅ 审查者亲跑：205 passed/3 deselected、ruff、format 双绿 |

## 审查过程备注（环境风险，记档）

首次红灯复核出现假绿：conda 环境的 editable 安装被 Codex 在 worktree 内 `pip install -e .`
重指向 `mqp-task-076`，主仓运行 pytest 实际 import 了分支代码。**多 worktree 共享一个 conda
env 时，`pip install -e` 指向以最后一次为准，跨 worktree 跑测试会串扰**。本次审查全部改用
显式 `PYTHONPATH=<目标>/src` 复跑后结论如上。根治：pyproject 增加
`[tool.pytest.ini_options] pythonpath = ["src"]`（rootdir 相对，每个 worktree 自动指向
自己的 src）——已开 TASK-077 工程卡。

## 语义影响记档

- 全部出场原因（信号/two_day_no_profit/max_hold/stop_loss）统一受跌停开盘 + 停牌顺延约束，
  研究引擎卖出语义自此与 Tier3（TASK-031）同构；
- R1 双线/短线存档数字自此不可复现（约束更严，方向只会更差或持平）——存档冻结，不重跑。

# TASK-022 Review（第 1 轮，PASS with reviewer fixup）

- 日期：2026-07-07　|　审查者：Claude (Fable 5)　|　分支：`task/TASK-022-b1`（7a6023e + 审查者修复 1e98259）

## 验收（审查者独立运行）

test_b1（9→修复后 10）+ 全套 + ruff 全绿；长 fixture `sz000001_long.day`（600 根）按指令新增、未触碰既有黄金；三预设参数与 b1.md 差异表逐格核对一致；默认版命中日快照（2022-12-19~21）合理。

## 审查者修复（fixup 1e98259，非返工）

**A1 布尔结构错误（or2 模式）**：v2.42b/p 的原式第二分支（YANGYIN_OK2）**不要求 THREE_SUM_OK**（逐字核对 Obsidian 原文确认），提交版把 three_sum 施加到了整个 or2 表达式 → b/p 变体比原式更严、少出信号。and3 模式的因式分解则完全正确。

处置：抽出 `_assemble_a1()` 纯函数（两模式共享 `common & ((ok1 & three_sum) | ok2)`，and3 额外要求 ok3），新增三预设真值表测试锁死结构。**归因说明**：卡面注释 "b/p: ok1|ok2" 未写明 three_sum 的分支归属，规划者对此错负一半责任——b1.md 与卡已同步修订。

## 质量意见

- MVOK/板块剔除正确留在 signals/universe 层（docstring 声明）；`signals/factors.py` 的市值组合封装接口合理。
- relaxed J 条件、GOOD28、MAXVOL_OK、HALF_DOWN 前提等构件与原式逐项一致。

**PASS**（含 fixup）—— 已合并。

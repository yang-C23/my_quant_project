# TASK-025 Review（第 1 轮，PASS with reviewer fixups）— 附 014/015/016/026 批次简评

- 日期：2026-07-07　|　审查者：Claude (Fable 5)

## TASK-025 事件研究引擎（gate 卡）

开发者提交的引擎结构、样本剔除计数、by_year/报告链路合格；单测/ruff 全绿。但小样本对拍未归零（589vs593、h1 差 19.82bps），审查者追根到**三处口径差**（全部修复，fixup 提交在案）：

1. **收益口径**：v1 = `close(entry+h)/open(entry)`（入场后再持 h 天）；提交版按平台文档写成 entry+h−1——**文档错**，已修订 backtest_platform.md §2/§5。
2. **过滤口径**：v1 KDJ 研究从不剔停牌/一字板 → 新增 `entry_filters="ashare"|"none"`（生产默认 ashare，parity 用 none）。
3. **信号源**：v1 kdj_j0 用简单均线 KDJ（bt.indicators.SMA）非 TDX 递归 → `kdj(sma_mode="simple")` parity 专用变体。

另修：CLI 单日时点宇宙（`at=end`）改为全期宇宙（**幸存者偏差**，实质正确性问题）；批量运行对窗口内无数据符号优雅跳过；`_load_prices` 并行化；**qlib init 线程竞态加双检锁**（20 线程并发 init 曾致 `KeyError: dataset_cache`）。

修复后 10 股对拍：**signals 2180=2180，h1/h3/h5 均值差 0.0000bps —— 引擎逐位等价**。全市场 gate 见 `M2-gate-report.md`（v1 原样宇宙重放；v1 宇宙含 2,393 个误分类非股票资产的发现与处置见该报告）。

## 批次简评

- **TASK-014** PASS：符号互转/三口径换算恒等式/stocks universe 测试齐全；qlib init 竞态由审查者补锁。
- **TASK-015** PASS：幂等/除权窗口整段重写用例扎实。
- **TASK-016** PASS + 审查者修 `itertuples` 对 `_merge` 列改名的崩溃 bug（在存在差异行时才触发——测试盲区）；C5 口径按 013 备注执行正确；ruff exclude 收窄完成。
- **TASK-026** PASS：IC≈1/随机≈0/前视保护/单调性用例齐全。

## 遗留（非阻塞）

- 全市场 study 运行 ~8 分钟（目标 2 分钟）：瓶颈是逐符号 qlib IO（×2 阶段）。已列为 R1 期间的性能卡候选（批量 D.features 一次加载可解）。
- factors.py 批量 concat 的 FutureWarning 待清。

**结论：五卡全部 PASS（含 fixups），已合并。**

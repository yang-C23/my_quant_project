# TASK-024 Review（第 1 轮）

- 日期：2026-07-07　|　审查者：Claude (Fable 5)　|　分支：`task/TASK-024-volume-brick`（3636fd1，堆叠于 022）

## 验收（审查者独立运行）

三个目标测试文件 15 passed；堆叠分支全量 81 passed；ruff 全绿；brick `zxt` vs 黄金 `bt_legacy_*.csv` rtol ≤1e-8 通过。

## 质量意见

- 砖形三变体共享骨架 + `BrickParams` 预设，与 brick.md 变体表一致；relaxed 的宽松超跌条件用 `EXIST(REF(J,1)<13, 3)` 因式化——与原式 `J1<13 OR J2<13 OR J3<13` 等价，验证认可。
- var1a/var3a 的除零包裹整个表达式（含 −90 偏移）——与 v1 bt `BrickIndicator` 一致，黄金锁定；与"纯 TDX /0→0 仅作用于除法"存在理论差异，但 4 根窗口 H==L 极罕见且黄金为准绳，接受并留档。
- `single_needle_proxy` 命名与 docstring 的"与指南针原版不等价 + 胜率~37%/盈亏比3:1 先验"声明齐全；倍量三明治/三连倍量的信号日=形态完成日（无前视）。
- 知行 MACD 直译正确（ewm adjust=False，零轴 cross 布尔）。

**PASS** —— 已合并。

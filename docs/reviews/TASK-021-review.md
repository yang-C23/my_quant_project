# TASK-021 Review（第 1 轮，规划者审查）

- 日期：2026-07-07　|　审查者：Claude (Fable 5)　|　分支：`task/TASK-021-kdj-dualtrend`（018bacf）
- 开发者自审报告见该分支上的同名文件（合并 v2 时以本文件为准）。

## 验收命令重跑结果

单测/ruff/黄金 `--check` 全部通过——但**测试通过不等于语义正确**，见下。

## 必须修改（CHANGES_REQUESTED）

### 1. [阻塞] 呼吸度语义错误：窗口内 top-3 ≠ 通达信字面语义

`_rolling_distinct_volume_breath` 用 `sliding_window_view` 在**当前窗口内**做去重 top-3——但通达信
`VH2:=HHV(IF(VOL<VH1,VOL,0),N)` 的 `IF` 是**逐 bar** 用**该 bar 自己的滚动 VH1** 掩蔽，再对掩蔽序列滚动求最大。两者不同：某 bar 若是"其自身回溯窗口的最大值"会被置 0，即使它只是当前窗口的第二高；反之当前窗口最大值若非其自身窗口最大，真语义下 VH2 会等于 VH1。

**审查者实证（fixture 数据）**：两种语义在 sh600000 上 149/171、sz000001 上 171/171 个 bar 不同，最大相对偏差 ~49%，`breath_active` 分别翻转 13/40 次——这是另一个指标，不是边界差异。

**修复：按字面嵌套滚动重写（参考实现，已验证可直接采用）：**
```python
SENT = 99_999_999.0
v = volume.astype(float)
vh1 = v.rolling(n).max()
vh2 = v.where(v < vh1, 0.0).rolling(n).max()
vh3 = v.where(v < vh2, 0.0).rolling(n).max()
vl1 = v.rolling(n).min()
vl2 = v.where(v > vl1, SENT).rolling(n).min()
vl3 = v.where(v > vl2, SENT).rolling(n).min()
avghigh = (vh1 + vh2 + vh3) / 3.0
avglow = (vl1 + vl2 + vl3) / 3.0
```
（删除 sliding_window_view 版本；比它还简单。）

### 2. [阻塞] RSV 除零口径与黄金相悖

`kdj.py` 用 `.where(denom != 0)` → NaN。TASK-020 review 第 3 条已实证：v1/黄金/通达信 `/0→0` 惯例均为 **RSV=0**。fixture 无一字板样本所以测试侥幸通过。改为 `F.IIF(denom == 0, 0.0, (close - low_n) / denom * 100.0)`（denom 为 NaN 的 warmup 区自然仍是 NaN），并新增微用例：构造连续 9 根 `H==L==C` 的一字窗口，断言 RSV 段为 0 且 K 递归照常。

### 3. 测试设计调整（随 1 而变）

- 删除"差异仅发生在窗口含重复量值日"的断言（那是 top-3 语义的预测，对字面语义不成立）；
- 新增：呼吸度 vs 测试内 ~15 行朴素逐 bar TDX 求值 oracle 全等（rtol 1e-10）；
- vs v1 sorted 黄金（`avghigh/avglow` 列）改为**统计记录**：打印差异 bar 数并存快照，不设通过阈值（语义定义不同，非 bug）。

### 4. 流程

修复前先 `git merge v2`：拿到 TASK-023 已合并的 `signals/registry.py`，把 `kdj_oversold`/`dual_trend_entry` 注册**并入现有文件**（与 amv 注册共存），`indicators/__init__.py` 同理；评审文件冲突以 v2 版为准。

## 认可项

kdj/dual_trend 的接口、白线/黄线/金叉死叉、registry 骨架、输入校验与测试结构都合格；白线对比窗口（bar≥150）处理正确。问题集中在两处语义，修完即收。

## 结论

**CHANGES_REQUESTED**（修改项 1–4）。

---

# 第 2 轮（返工审查，2026-07-07）

审查者独立重跑：11 指标测试 + 53 全套 + ruff + golden `--check` 全绿。**恒等复核**：`_rolling_tdx_volume_breath` 与审查者的字面语义参考实现在两只 fixture 上逐位一致（rtol 1e-12）；一字板窗口（12 根 H==L==C）RSV=0、K 恒 0 行为正确；registry 与 amv 注册共存无冲突。开发者留档的 v1 sorted 差异快照（149/171、171/171，active 翻转 13/40）与审查者第 1 轮实证完全吻合。修改项 1–4 全部落实。

**PASS** —— 已合并至 v2。

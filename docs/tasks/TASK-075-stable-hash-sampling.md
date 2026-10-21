# TASK-075: 稳定哈希抽样（universe 无关采样）

- Milestone: M3.5　|　State: ready（白名单与 032/071/073/074/076 零交集，可并行开发）
- Branch: `task/TASK-075-stable-hash-sampling`　|　Depends: —

## Context
ADR-0005 §3。`optimize.sample_symbols` 现按整数位置 `rng.choice(len(ordered), …)` 抽样：
审查者实测 universe 5465→5466 中部插 1 只后，seed=42 的 800 样本**被换掉 368 只**——
R1 勘误 3 的 turnover_cost w60 decision 翻案即此机制。二元 gate 对样本组成极敏感，
抽样必须对 universe 增删稳定。

## Goal
同签名下 `sample_symbols` 改为 symbol 级稳定哈希：乱序输入结果逐位不变；universe
增/删 1 只时既有样本最多变 1 个成员；分布近均匀（防 F-1 头部/字典序截断死灰复燃）。

## Scope
1. `src/quant/research/optimize.py::sample_symbols(symbols, max_symbols, seed=42)`
   **签名不变**，内部改为：
   ```python
   score(symbol) = hashlib.sha256(f"sample_hash_v1|{seed}|{symbol}".encode()).hexdigest()
   ```
   取 score 最小的 K 个，返回按 symbol 字典序（与 `list_symbols` 输出序一致）。
   **禁用内建 `hash()`**（进程随机盐，跨进程不可复现）。docstring 更新：写明 policy 版本
   字符串 `sample_hash_v1`、以及"R1 存档用旧位置算法，此后不可复现属预期"。
2. 调用方（exploratory/trade_pairs）零改动——签名兼容，它们不在白名单，改了=越界。
3. `tests/unit/test_optimize.py`：三条变形测试 + 均匀性反截断用例（见 AC）。

## Non-goals
分层抽样（板 × 市值 × 流动性，M3.5 二批）；不改任何调用方；不重跑 R1；不加 CLI。

## Files to touch
- `src/quant/research/optimize.py`
- `tests/unit/test_optimize.py`

## Acceptance criteria
1. 变形测试（新用例，`pytest -q tests/unit/test_optimize.py` 全绿）：
   - a. 乱序不变：`sample_symbols(shuffled(u), k, s) == sample_symbols(u, k, s)`（列表逐位相等）；
   - b. ±1 稳定：5465 只合成 universe 任插 1 只后重抽，`len(set(old) & set(new)) >= k−1`；
     任删既有 1 只同理；且**枚举 ≥200 个候选插入符号，至少一个换入事件发生且换入的正是
     新 symbol**（防"永远返回同一批"的退化实现）；
   - c. 确定性：同输入两次调用逐位相等；`seed=42` 与 `seed=43` 结果不同。
2. 均匀性反截断：构造三前缀组 universe（`bj*` 1000 只、`sh*` 2000 只、`sz*` 2000 只），
   k=800——断言入选数 `bj ∈ [108, 212]`、`sh ∈ [256, 384]`、`sz ∈ [256, 384]`
   （超几何 ±5σ，规划者手算界写死用例）。字典序头部截断（bj 全选）必挂。
3. 既有 `sample_symbols` 相关断言若编码旧算法的具体成员，更新处列清单进 STATUS 备注。
4. `pytest -q -m "not integration"` + `ruff check .` + `ruff format --check .` 全绿。

## 验收如何被作弊/退化满足？
1. **排序头截断**（F-1 变种）能同时通过乱序不变与 ±1 稳定——AC2 均匀性界钉死
   （bj 组入选 800 或 0 都必挂）。
2. **内建 `hash()` 图省事**：跨进程不可复现——审查者用不同 `PYTHONHASHSEED` 双进程复跑
   AC1c 核对逐位一致。
3. **改调用方凑绿**：白名单只有两个文件，`check_whitelist.py` 拦。
4. **"永远返回同一批"**（无视新 symbol）可骗过交集 ≥ k−1——AC1b 的换入事件断言钉死。
5. **均匀性界放宽**：界值由规划者手算写死在卡面（超几何 σ：bj≈10.4、sh/sz≈12.7），
   diff 中出现别的数字=打回。

## 数值验证类别与变形测试
Class A（确定性哈希，逐位可复现）。变形测试即 AC1 a/b/c + AC2（乱序不变、±1 最多换 1、
跨进程确定性、分布均匀）。

## Test plan
纯合成 universe 单测，无真实数据。既有 seeded-random 用例按 AC3 清单化更新。

## Notes / risks
- **合并顺序：071 先于本卡**——071 的 AC1 以 v2 基线 CSV 逐位对照，其基线含旧抽样；
  本卡若先合入 v2 会使对照口径错位。开发可并行，合并排队由规划者控制。
- 本卡合并后任何 800 样本重跑与 R1 存档不可比（存档冻结，勘误 3 已记）。
- 030/034 等全 universe 基线不受影响（不经 `sample_symbols`）。

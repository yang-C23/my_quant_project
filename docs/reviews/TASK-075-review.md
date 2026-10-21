# TASK-075 Review — 稳定哈希抽样（universe 无关采样）

- 分支：`task/TASK-075-stable-hash-sampling`（e13251c）
- 审查者：Claude（规划/审查代理）
- 日期：2026-07-11
- 结论：**PASS（合并排队：071 先合，本分支勿动）**

## 验证

| 项 | 结果 |
|---|---|
| 白名单 | ✅ 3 文件，check_whitelist OK |
| 实现 | ✅ `hashlib.sha256(f"sample_hash_v1\|{seed}\|{symbol}")` 取 score 最小 K、返回 symbol 字典序；无内建 `hash()`；docstring 含 policy 版本与"R1 存档不可复现属预期" |
| AC1 变形测试 | ✅ 乱序不变（逐位）、+1/−1 交集 ≥ k−1、200 候选换入事件（换入者恰为新 symbol 且恰换 1 个）、seed 42≠43 |
| AC2 均匀性 | ✅ 界值与卡面逐字一致（bj∈[108,212]、sh/sz∈[256,384]），头部截断必挂 |
| 跨进程确定性 | ✅ 审查者以 `PYTHONHASHSEED=0/12345` 两进程运行 5465→800 抽样，结果 sha256 指纹逐位相同（e0c059406cfc0c51） |
| AC3 | ✅ 旧测试无旧算法具体成员断言（STATUS 备注与 diff 核对一致，旧用例被等价替换并加强） |
| 质量门 | ✅ 审查者亲跑：目标 8 passed、全量 204 passed/3 deselected、ruff、format 双绿 |

## 备注

- 附带语义变化（可接受，已有测试编码）：`max_symbols=None`/超界时返回 `sorted(symbols)`
  而非保留输入序——调用方 `list_symbols` 输出本就有序，无实际影响。
- **合并排队**：TASK-071 的 AC1 以 v2 基线 CSV 逐位对照，基线含旧位置抽样——本分支必须在
  071 合并之后再合，否则对照口径错位。071 过审当轮由规划者一并合并本分支。

# TASK-068 Review — R1 协议一致性修复（入场严格 t+1 + 065 ashare）

- 分支：`task/TASK-068-r1-protocol-fixes`（e5b96f6）
- 审查者：Claude（规划/审查代理）
- 日期：2026-07-09
- 结论：**PASS**（全部 AC 通过；审查者独立红灯复核 + 三条 IS 同配置复跑数字与 findings 增补表逐项吻合；无结论翻转）

## 白名单与范围

- 8 个改动文件全部在卡面白名单内（`scripts/check_whitelist.py --base v2` 通过）。
- STATUS 变更仅为开发者被允许的 `ready→review` 行内更新。
- Scope 对照：入场改严格 `signal_pos+1`、`entry_suspended`/`entry_limit_up` 分桶命名与 forward_returns 参照完全一致；`entry_filters="none"` 保留 parity 语义（open NaN → entry_missing）；**出场顺延逻辑未动**（卡面明令保留）；exploratory `_load_prices` 走 067 的 `get_ohlcv_batch`（qfq + raw 旗标 merge，照抄 forward_returns 口径）；`_top_quantile_event` 改传 `entry_filters="ashare"`。

## 反作弊栏逐条核销

| 卡面攻击面 | 核销结果 |
|---|---|
| 1 键名换皮 | 新用例断言 `entry_suspended==1` 且 `entry_missing==0`、`trades.empty`——剔除行为本身被断言，非仅键存在 |
| 2 恒真用例 | **审查者独立红灯复核**：将 src 两文件回退到 v2 后跑新测试 → 恰好 3 failed（两个入场剔除 + 一个 exploratory 过滤），恢复后 17 passed。与 Codex 自述红→绿一致 |
| 3 过滤加错层 | exploratory 用例直接调用生产函数 `_top_quantile_event`，喂含停牌/一字板原始帧，断言 avg=0.05 / PF=2.0（手算可验） |
| 4 复跑造假/换样本 | 配置零改动（diff 不含 configs/）；审查者同配置独立复跑三条命令比对 findings 数字（见下） |
| 5 翻转措辞掩盖 | 三份增补表新旧并排：063 dead_cross 仍最优（PF 1.147→1.140）、064 仍费前近噪声、065 全部仍 invalid_or_uncertain——无翻转 |
| 6 误改出场语义 | 既有 `test_exit_suspension_defers_to_next_open` 未改且通过；出场侧 diff 为零 |

## 验收命令复跑（审查者亲自执行）

| AC | 命令 | 结果 |
|---|---|---|
| 1 | `pytest -q tests/unit/test_trade_pairs.py` | ✅ 11 passed（含红灯复核） |
| 2 | `pytest -q tests/unit/test_exploratory_factors.py` | ✅ 6 passed |
| 3 | 三条 `myquant research` + findings 增补节 | ✅ 审查者同配置独立复跑（dual 351s / shortterm 442s / exploratory 718s），关键行与增补表逐项吻合：063 golden×dead 5240 笔/PF 1.1398/median −0.0440、dual_entry×dead 3189 笔/PF 1.149；064 single_needle hold=1 404 笔/PF 1.159；065 washout w20/w40/w60 top_h5 0.0040/0.0044/0.0040、PF 1.170/1.188/1.173，全部因子仍 invalid_or_uncertain |
| 4 | `pytest -q -m "not integration"` + `ruff check .` | ✅ 172 passed, 3 deselected / All checks passed |

## 红线核查

- IS 段纪律：diff 中唯一 2021 后日期为卡面要求的增补节标题"2026-07"；configs 未动；OOS 未跑（由审查者本文件下方处理）。
- `ruff format --check .` 残余失败 = TASK-069 已记录的 5 个既有债务文件，本卡白名单外，不构成打回理由。

## OOS 勘误核对（审查者职责，非本卡范围）

合并后审查者重跑 `scripts/r1_oos_final.py --i-am-the-reviewer`（58s，067 批量 IO 后大幅提速）：

- AMV 主裁定表**逐位不变**（指数择时引擎不受入场修复影响）；
- 双线基线留档表 4260→4259 笔、PF 1.0121→1.0129，方向不变；
- **R1"零候选进入 Tier3"最终裁定维持**。勘误节已追加至 `docs/reviews/R1-final-report.md`。

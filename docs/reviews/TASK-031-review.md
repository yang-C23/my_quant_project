# TASK-031 Review — Backtrader A股基础件（costs / feed / constraints）

- 分支：`task/TASK-031-bt-feed-constraints`（5c9b6ef）
- 审查者：Claude（规划/审查代理）
- 日期：2026-07-09
- 结论：**PASS**

## 验收命令复跑（审查者亲自执行）

| AC | 结果 |
|---|---|
| 1 费用单测 | ✅ 期望值为手算字面量且审查者按 §3 独立复算：买 100@10=5.01（最低佣金触发）、卖=5.51、买 1000@100=26.00、卖=76.00、桥接切换前卖=6.01 |
| 2 约束单测 | ✅ T+1 当日拒/次日放、一字涨停拒/盘中触板放/正常放（成对断言）、一字跌停卖拒、停牌双向拒、round_lots(150)=100/(99)=0 |
| 3 cerebro 冒烟 | ✅ 佣金桥实际挂接 broker；期末现金 8994.99（买入持有）/9989.48（含印花往返）逐项手算注释，审查者复算一致 |
| 4 全量 | ✅ 201 passed / ruff check / ruff format --check / 硬编码 gate 全绿；白名单 9/9 |

## 反作弊栏核销

1 期望值同源——全部字面量，未调用被测函数生成 expected；2 恒真约束——每场景成对断言（拒+放）；3 税率特判——参数化覆盖切换日前后各两日+当日（`<cutover→1e-3` 即 2023-08-28 当日生效新率，与公告一致）；4 自算涨跌停——判定只读 `raw_open`/`limit_*_price` 列，无 10%/20% 重算；5 佣金桥未挂接——`addcommissioninfo` 真实挂接 + 期末现金含费明细；6 NaN 哨兵——**-1 仅用于 is_suspended**（缺失→双向拒绝，有专门用例）；limit 价缺失保持 NaN → `isfinite` 判 None → 跳过限价检查，语义分层干净且写入 docstring。

## 设计要点与遗留提示（给 TASK-032）

- `AShareCommission._getcommission` 拿不到成交日期（backtrader 限制），结算日靠
  `set_trade_date()` 显式喂入，默认 2023-08-28 后新税率。**032 的 parity 窗口在 2023-08-28
  之前（印花 0.1%）——策略侧必须逐 bar `set_trade_date`，否则每笔卖出费差 0.05%，
  会直接吃掉"均值≤5bps"的 parity 容差。此提示已写入 032 卡。**
- feed 保留停牌 bar（价格 ffill、volume=0、旗标标记），与 v1 做法对齐；前导缺价保持 NaN。
- `slippage_rate` 为同源常量，backtrader 侧由 032 用 `set_slippage_perc` 挂接（本卡 Notes 约定）。

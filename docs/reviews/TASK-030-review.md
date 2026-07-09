# TASK-030 Review — qlib TopkDropout 基线 + mlflow

- 分支：`task/TASK-030-qlib-topk-baseline`（5f003f2）
- 审查者：Claude（规划/审查代理）
- 日期：2026-07-09
- 结论：**PASS（管线交付合格）**，但**基线 metrics 判定无效**——审查中发现白名单外的既有数据层缺陷（见下"重大发现"），已开 TASK-070 修复；070 合并后须重跑基线并更新 mlflow/报告。

## 验收命令复跑（审查者亲自执行）

| AC | 结果 |
|---|---|
| 1 跑通 + 耗时 | ✅ 审查者两次独立完整运行 67.2s / 66.1s（Codex 报 64s 量级吻合） |
| 2 mlflow | ✅ 两个新 run（3ed48c…、1269b0…）经 MlflowClient 可查，params 含全部配置 + universe.symbol_count |
| 3 确定性 | ✅ 两次完整命令、不同 run_id、metrics **12 位有效数字逐位一致**（PYTHONHASHSEED=0 子进程方案有效，递归护栏依赖 067 的 `__main__` 守卫） |
| 4 单测 | ✅ 8 passed；含"配置=卡面默认"钉死用例与 mom_20 尾行扰动用例（手算值 20.0 断言） |
| 5 全量 | ✅ 180 passed / ruff check / ruff format --check 均绿 |
| 白名单 | ✅ 9 文件全在卡内（含卡面授权的 pyproject `mlflow>=2,<3` 单行；mlflow 3.x 拒绝 filesystem tracking URI，锁 2.x 合理） |

## 反作弊栏核销

1 缩水配置——config 与卡面默认逐项一致且有单测钉死；2 确定性假验证——审查者亲自双跑；3 mlflow 手灌——metrics 与报告 CSV 同一 dict 落盘（代码路径同源）；4 费率——卡面四元组写入报告头；5 mom_20 未来函数——尾行扰动用例；6 批量 IO——因子走 `compute_factor_frame`。

## 重大发现（审查副产物，缺陷在本卡白名单之外）

基线 metrics 物理不可能（annualized_return 17.11=1711%、max_drawdown −1.16=−116%、单日收益最高 +5399%、69/1706 天 |return|>11%）。审查者定位根因：

- `staging.py::_classify_security` 兜底分支把未识别前缀一律归 `("stock","other")`；
- 258 个 TDX 有 .day 无元数据的历史代码（sh111xxx 老国债、sz131/sh204 回购、sh520/sz184 老基金等，name 全为 None）被标成 sec_type=stock；
- `list_symbols(exclude_boards={"star","b"})` 因此放行它们进 universe；回购"价格"是利率报价（单日 +68490%），mom_20 topk 直接吃进爆点。
- **连带影响 R1**：seed=42 的 800 股样本经复现含 **39 个此类代码（4.9%）**。R1 结论均为阴性、AMV 主裁定走指数不受影响，但 063/064/065 的股票池统计受噪声污染——TASK-070 合并后由审查者做敏感性复跑并决定是否勘误（同 F-1/F-2 处置模式）。

030 的实现无法也不应在本卡内修此缺陷（`staging.py`/`universe.py` 不在白名单）；管线代码本身经上表验证合格，故合并，基线数字以 070 修复后重跑为准。

## 待办（规划者）

1. TASK-070（分类修复 + 元数据再生）已开卡置 ready；
2. 070 done 后：重跑 `myquant backtest topk configs/backtest/topk_baseline.yaml` 双次，更新本报告附录与 STATUS 备注；
3. 070 done 后：R1 敏感性复跑（IS 三卡 + OOS 脚本），出勘误决定；
4. TASK-034（AMV 仓位开关）在基线数字有效前不开卡。

## 附录（2026-07-09，TASK-070 合并后基线重跑）

净化 universe（5465 只）上双次完整重跑，metrics 逐位一致（run def63498…等）：

| metric | 污染前（无效） | 净化后（**有效基线**） |
|---|---:|---:|
| annualized_return | 17.11 | **−0.1664** |
| information_ratio | 0.738 | **−0.770** |
| max_drawdown（累加口径） | −1.161 | **−2.252** |
| turnover_mean | 0.2356 | **0.0667** |
| excess_return_wo_cost | 17.13 | **−0.1921** |
| excess_return_with_cost | 17.07 | **−0.2080** |

有效性判定依据：单日收益 0 天超出 ±11%；极值日逐一对应真实市场事件（2016-01-04/07 熔断、
2015-06-26 股灾、2020-02-03 疫情开盘）。注意 qlib `risk_analysis` 的 max_drawdown 为**累计加和**
口径（非复利），7 年累加收益 −1.08 下 −2.25 合法——本报告正文早前"物理不可能"的表述仅适用于
复利口径，于加和口径不成立，特此修正。

mom_20 topk50 在 IS 段大幅跑输基准与"A股反转强、短窗动量弱"的共识一致；本卡目标是管线
基线而非 alpha，**管线判定：有效可用**。TASK-034（AMV 仓位开关）解除阻塞。

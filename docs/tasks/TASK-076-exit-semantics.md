# TASK-076: trade_pairs 退出语义统一（跌停/停牌约束 + MAE/MFE 顺延窗口）

- Milestone: M3.5　|　State: ready（`trade_pairs.py` 不在 032/071 白名单，可并行开发）
- Branch: `task/TASK-076-exit-semantics`　|　Depends: —

## Context
ADR-0005 §7。现实现 `_exit_trade` 仅 `exit_reason == "stop_loss"` 时
`block_limit_down=True`（trade_pairs.py:308）：死叉等信号出场、`two_day_no_profit`、
`max_hold` 出场可在一字跌停开盘"成交"——违反不可成交红线的对称性（现实中跌停开盘
挡的是所有卖单，不看你的卖出理由）。另 F-7 已知口径：MAE/MFE 只统计到出场信号日
（`held = bars[entry_pos : exit_signal_pos+1]`），停牌/跌停顺延期间的尾部风险漏计。
附带清理：`_next_tradable_pos` 的 ashare 分支两侧同 `return pos`（死代码，现仅以
`entry_filters="none"` 被调用）。

## Goal
全部出场原因统一受跌停开盘/停牌约束顺延；MAE/MFE 覆盖至真实出场执行；死代码清除。
研究引擎卖出语义自此与 Tier3 backtrader 约束（TASK-031）对齐。

## Scope
1. `_exit_trade`：`exit_exec_pos = _next_tradable_pos(bars, exit_signal_pos+1,
   block_limit_down=True)`——**所有 exit_reason 一致，无条件分支**。
2. `_next_tradable_pos`：删除 `entry_filters` 参数与死分支（该函数只服务出场路径）。
3. MAE/MFE 顺延窗口：`held = bars.iloc[entry_pos : exit_exec_pos]`（覆盖顺延期间全部
   完整持有 bar，Python 切片右开=至 exec−1），且
   `mae = min(held["low"].min(), exit_price) / entry_price − 1`、
   `mfe = max(held["high"].max(), exit_price) / entry_price − 1`（出场执行价计入两侧极值）。
4. `tests/unit/test_trade_pairs.py`：新边界用例 + 既有断言按清单更新。

## Non-goals
不改入场语义（TASK-068 已修）；不加费用/滑点；不动 `forward_returns`/`ic`/`optimize`；
不改 `run_dual_trend_research`/`run_shortterm_research` 的研究配置与网格。

## Files to touch
- `src/quant/research/trade_pairs.py`
- `tests/unit/test_trade_pairs.py`

## Acceptance criteria
1. 新用例（构造数据手算，Class A）：
   - a. **信号出场遇跌停**：死叉出场信号次日 `raw_open <= limit_down_price` → 顺延至
     下一非跌停可交易日开盘成交；`exit_date`/`exit_price`/`return` 断言手算值。
     **本用例在改动前代码上必须失败**（审查者红灯复核）。
   - b. **max_hold 出场遇跌停**：同 a 构造，reason=`max_hold` 也被阻塞顺延。
   - c. **顺延期间 MAE**：顺延窗口内出现更低 low → `mae` 按顺延窗口最低点手算；
     另一变体：`exit_price` 低于持有期全部 low → `mae = exit_price/entry_price − 1`。
   - d. 停牌顺延既有语义不回归（既有用例保持绿）。
2. 既有断言若编码旧 MAE/MFE 或旧出场值，更新处列清单进 STATUS 备注
   （旧值 → 新值 → 手算依据），清单外断言改动=打回。
3. `grep -n "entry_filters" src/quant/research/trade_pairs.py` 显示 `_next_tradable_pos`
   签名已无该参数（入场侧 `run_pair_study(entry_filters=…)` 保留不动）。
4. `pytest -q -m "not integration"` + `ruff check .` + `ruff format --check .` 全绿。

## 验收如何被作弊/退化满足？
1. **只对 dead_cross 加约束、漏 max_hold/two_day_no_profit**：AC1a/1b 分 reason 构造；
   审查者 diff 核对 `block_limit_down` 处**无 reason 条件分支**。
2. **MAE 窗口只延到 exec−1 不含 exit_price、或只用 exit_price 不看窗口**：AC1c 两个方向
   各有手算断言。
3. **用 qfq 价比对跌停价**（复权价与 limit 价不可比，必假阴性恒不阻塞）：用例必须构造
   `raw_open`/`limit_down_price` 字段（与 `_load_prices_batch` 真实列名同名）且断言
   阻塞确实发生（顺延日数 >0），防空转。
4. **红灯复核**：AC1a 在旧代码必须红——审查者亲自回退验证（同 070/072 模式）。
5. **删参数但留死逻辑**：AC3 grep 钉死签名；审查者 diff 核对无残留分支。

## 数值验证类别与变形测试
Class A（构造数据手算）。变形测试：制造跌停出场日 → 不得按不可成交价卖出（AC1a/b）；
制造停牌期间下跌 → MAE 不得忽略顺延风险（AC1c）；出场约束收紧后每笔 `exit_date` 只会
不早于旧实现（用例内对比断言可选）。

## Test plan
纯构造数据单测（合成 bars 含 `raw_open`/`limit_down_price`/`is_suspended` 列）；
无真实数据依赖。

## Notes / risks
- 本卡后 R1 双线/短线存档数字不可复现（方向必然是 PF/avg 变差或持平——约束只会更严）；
  存档冻结不重跑。
- `two_day_no_profit` 出场同样顺延——此后研究引擎与 Tier3 卖出约束完全同构，
  Tier2→Tier3 的费前/费后差异不再混入执行语义差异。

# TASK-032 Review（第一轮）— DualTrend bt 移植 + parity

- 分支：`task/TASK-032-dualtrend-bt-parity`（3d9c2d1）
- 审查者：Claude（规划/审查代理）
- 日期：2026-07-10
- 结论：**changes_requested**——交付纪律满分（判据未放宽、全量跑完、诊断到位、停下等裁定），
  但 parity 失败的三条根因已由审查者定位，均可修，返工项见下。

## 交付面核查（本轮已合格的部分）

- 白名单/ruff/format/硬编码 gate/209 单测全绿；10 股 smoke 13.92s PASS；
- `compare_parity.py` 判据硬编码未放宽（反作弊 1 ✓）；黄金 CSV 未动（反作弊 2 ✓）；
- 差异如实全量上报 STATUS（协议模范执行）。

## 根因裁定（审查者独立验证）

| 轴 | 证据 | 结论 |
|---|---|---|
| A. universe 错配（symbols 5508/4564，extra 946 / missing 2） | v1 universe 来自 PG securities 自有分类；missing `sh689009` 九号公司=科创 CDR（v2 star 被排除、v1 不识 689）；missing `sz302132` 中航成飞=**070 兜底把 302 新号段误分 other**（审查者已确认，另开 TASK-072 修分类器本体） | parity 不应重建 v1 过滤逻辑，**直接钉死黄金 CSV 的 4564 只符号集** |
| B. bar 流语义（signals 163853/42637 ≈ 3.8×） | v1 从 PG `v_qfq_daily` 读，**只有真实成交行、无日历填充**（`git show 53f72fd^:src/quant/data/loader.py` L33，审查者复核）；v2 数据路径保留停牌/缺数日历行并 ffill 价格 → 指标流被人造平价 bar 污染，KDJ 在长平价窗上批量产生假 J<13 信号 | parity 模式指标流**只喂真实成交 bar**（剔除 suspended/无成交行），对齐 PG 语义 |
| C. RSV 零分母崩溃 | v1 原版策略在当前含 ffill 平价窗的 bar 流上 9 日 HHV−LLV=0 → 崩溃；修复 B 后平价窗大幅减少 | parity 模式 RSV **逐条复刻 v1**；修完 B 若仍在真实一字板连板窗崩溃，停下把符号+日期窗写 STATUS 等裁定——**不许自行发明 safe RSV 语义进 parity**（safe 版只准用于生产模式） |

M2 已知的减法/乘法 qfq 差异（~2.3% 信号扰动）仍可能残留——A/B/C 修完后若判据仍超差，
按卡面条款写逐项差异分析置 review，由规划者对照 TASK-025 的口径处理路径裁定。

## 返工项（在原分支继续）

1. parity config 增加从黄金 CSV 提取符号集（4564 只，排除 `ALL` 行），parity 运行不走
   `list_symbols` 板别过滤；
2. parity 数据准备剔除非成交 bar（`is_suspended==1` 或原始行缺失的日历行），生产模式路径不变；
   新增单测：含停牌段的合成序列，parity 流 bar 数=成交日数、指标值与"无停牌版"逐位一致；
3. RSV 恢复 v1 原版口径（parity 模式），safe RSV 移到生产模式分支；若全量仍崩溃→停下报告；
4. 重跑全量 parity + `compare_parity.py`，判据不变；耗时/结果更新 STATUS。

## 关联动作（不在本卡内）

- TASK-072（已开卡）：分类器补 302/201/395 号段，根修 universe 漏股；
- 072 合并后审查者重跑 030 基线双次并更新附录锚点（universe +1 股）。

## 第一轮裁定补充（2026-07-10，审查者调查结论——黄金参照更换）

返工后全量在 `sh600602` 1992-01-24 RSV 零分母崩溃即停（协议正确执行）。审查者深挖后裁定链：

1. **v1 的 `bt.If(denom==0, 0.0, …)` 在 backtrader 中不防除零**（双分支均逐 bar 求值）——
   审查者用合成 9 日平价窗实证 v1 KDJ 原码崩溃；
2. v1 靠 **engine 层 `except Exception → Skip → continue`** 存活，被跳符号不进黄金——
   审查者用 v1 原码 × PG 实证 sh600602 全历史 = 除零跳过（0 结果）；
3. 但 sh600602 在 2 月黄金里有行 → 2 月黄金带了未知 start；且 4 个 start 探测均无法复现其
   黄金行数字 → 更深根因：**PG 冻结于 2026-03-11，2 月 24 日后有 223 条除权事件**，
   v_qfq 视图全历史重算+舍入 → **2 月黄金在冻结快照上连 v1 自身都不可复现**；
4. 第一次重生成暴露 PG 元数据自身脏（sec_type=stock 返回 8016 只含利率类垃圾码）→
   总体改为**显式钉死 v2 canonical universe（5466 只）**。

**新黄金**：`docs/parity/dualtrend_breath_full_20260710_124211_summary.csv`
（v1 原码 main@f132436 × 冻结 PG，start=2015-01-01，end=2026-03-11，输入名单 5466 →
存活 5305 只 / 97,672 信号 / h1 win 49.43% avg 0.233%；160 只窗口数据不足、1 只 sz000937
除零跳过）。旧黄金废弃留档，README 已更新。

## 第二轮返工项（替换第一轮返工项 1/3/4）

1. `configs/backtest/dualtrend_parity.yaml`：`golden_csv` 指向新黄金；`start: 2015-01-01`、
   `end: 2026-03-11`；符号集仍从黄金 CSV 提取（现为 5305 只）。
2. **RSV 裁定落地**：parity KDJ 保持 v1 字面 `bt.If` 表达式**不加保护**；在 runner 的逐符号
   循环加 v1 engine 同款 `try/except Exception → 记日志 → skip`（跳过语义即 v1 语义）。
   被跳符号如出现在黄金内，`compare_parity.py` 的总体一致性检查会将其列为 missing——
   如实上报，不许静默。
3. 轴 B（只喂真实成交 bar）维持第一轮实现不变。
4. 重跑全量 parity + `compare_parity.py`，判据不变（count 全等 / 0.1pp / 5bps）。

## 第三轮裁定（2026-07-11，审查者独立复跑 + 三组对照实验后的根因分解）

二轮交付本身合格：三项返工全部落实（黄金符号集提取 / RSV 字面 bt.If + engine 级跳过 /
真实 bar 过滤），判据未放宽，FAIL 如实上报。审查者独立复跑**逐位复现** Codex 数字
（净 −1069、617 只差异符号、max |Δ|=13、win ≤0.05pp、avg ≤4.14bps），确定性成立。
随后两组对照实验完成根因分解：

| 实验 | 配置 | 净差 | 结论 |
|---|---|---|---|
| run 1 | 二轮交付原样 | −1069（493 负 : 124 正） | 基线 |
| run 2 | 审查者补丁：parity feed 旗标清零 | −698 | **旗标差解释 371 个信号** |
| 输入对照 | sh603019 PG v_qfq vs v2 qfq | 2690 根 bar **零根相同** | close 平均相对差 2.1%（max 11.8%）；**volume 差至 4×**（PG 视图对量也复权） |
| 920 段 | 41 只差异符号 | +87 | PG 无改码前历史（如 bj920974 缺 2021-08~2023-03 共 192 根），v2/TDX 并入全历史 |

**根因三分**（全部是输入差异或 v1 运行时语义复刻问题，非引擎移植 bug）：

1. **v1 的 `filter_untradable` 是运行时空转**：v1 `load_symbol_db` 只查 OHLCV 六列，
   `build_data_feed` 把 `is_suspended/is_upper_limit/is_lower_limit` **全部填常数 0**
   （审查者读 `53f72fd^:src/quant/data/loader.py` 实证）——黄金从未剔除过任何信号；
   v2 用真实旗标真剔 → 单向 −371。
2. **输入流每根 bar 都不同**：PG v_qfq 为减法式且**对 volume 也做调整**，v2 为乘法
   qfq + 原始 volume——KDJ/均线/双量启动/呼吸度全部吃到不同输入（M2 判例同款现象，
   当年 KDJ 上 −2.3%）。
3. **920 段覆盖差**：PG 只有北交所改码后历史（279 只在黄金内，41 只受影响，+87）。

**裁定**：按 M2 gate 判例执行（M2-gate-report：同 PG 输入 → count 全等证引擎；qlib 输入
差异单独量化归档为定义差）。**判据数字不变（count 全等 / 0.1pp / 5bps），改变的是对照
输入源**——这是隔离变量的修正，不是放宽容差。

## 第三轮返工项（原分支继续；卡面已由规划者同步修订）

1. `dualtrend.py`：把逐符号 cerebro 循环抽出为公共入口
   `run_dualtrend_from_frames(frames, params, *, parity_mode, report_dir, report_prefix)`
   （`run_dualtrend_backtest` 行为不变，内部改调它）；parity 分支的 feed 旗标清零
   （审查者 run 2 补丁语义：`suspended=0.0, limit_up/down_price=NaN`，复刻 v1 空转；
   生产模式真实旗标不动），加单测断言 parity feed 三旗标恒不阻塞。
2. 新建 `scripts/dualtrend_pg_parity.py`（psycopg2 只准出现在 scripts/ 层，守 033 的
   `grep psycopg2 src/` 红线）：对黄金 5305 符号逐只按 **v1 原路径**加载 PG
   `v_qfq_daily`（cursor + `pd.to_numeric`，`ORDER BY date`，OHLCV+amount），
   `raw_open=open`、旗标零值合成 feed 帧，调 `run_dualtrend_from_frames`
   （parity 参数同 yaml），产出 `dualtrend_pg_parity_summary.csv`。
3. **验收变更**：`scripts/compare_parity.py <pg_parity_summary> <golden>` 必须
   **signals/count 全等 + 0.1pp/5bps** → PASS（同码同源，再对不齐=移植 bug，回来修）；
   原 qlib 输入全量 run 保留执行一次，其 FAIL 数字（−1069/−698 分解）作为
   **定义差量化记录**写入 STATUS 备注归档（M2 报告 §"v2 自己的 qlib 数据"同款结构）。
4. 耗时与两组数字更新 STATUS；质量门全绿。

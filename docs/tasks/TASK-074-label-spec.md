# TASK-074: 研究语义契约 — LabelSpec 统一 Tier1/IC 标签

- Milestone: M3.5　|　State: backlog（Depends: TASK-071——白名单同碰 `ic.py`/`forward_returns.py`，071 合并后由规划者置 ready）
- Branch: `task/TASK-074-label-spec`　|　Depends: TASK-071

## Context
ADR-0005 §2。审查者实测（合成 12 bar 等差序列）：同 h=5，`run_event_study` 出场
`close(entry_pos+5)`（ret 0.054726），`ic._forward_returns` 出场 `close(entry_pos+4)`
（ret 0.044776，`horizon-1` 差一个 bar）；且 IC 路径无停牌/一字涨停入场过滤，
`_load_prices_for_factor` 连相关字段都不加载。两模块对"h 日收益"给出不同数字——
同一指标在 Tier1 与 IC 结论不一致时无法判断是信号问题还是标签问题；M6 模型标签
也将无口径可依。

## Goal
单一 `LabelSpec` 成为事件研究与 IC 共同引用的口径事实源：同一
(symbol, signal_date, h, spec) 下两模块 forward return **逐位相等**；一切研究产物带
spec hash。

## Scope
1. 新建 `src/quant/research/semantics.py`：
   ```python
   @dataclass(frozen=True)
   class LabelSpec:
       horizon: int
       signal_time: Literal["close_t"] = "close_t"
       entry_price: Literal["open_t_plus_1"] = "open_t_plus_1"
       horizon_counting: Literal["after_entry"] = "after_entry"  # exit bar = entry_pos + horizon
       exit_mark: Literal["close"] = "close"
       entry_tradability: Literal["ashare", "none"] = "ashare"
       adjustment: Literal["qfq"] = "qfq"

       def spec_hash(self) -> str: ...  # sha256(canonical repr) 前 12 hex，字段序固定
   ```
2. `src/quant/research/ic.py`（在 071 向量化代码上做，不许回退逐行循环）：
   - `_forward_returns` 接受 `spec: LabelSpec`：`exit_pos = entry_pos + spec.horizon`
     （对齐 after_entry，消除 `-1`）；
   - `spec.entry_tradability == "ashare"` 时按事件研究同款入场过滤：entry bar
     `is_suspended` 或 open 为 NaN → 剔除；`raw_open >= limit_up_price` → 剔除
     （列缺失按 `forward_returns._normalize_prices` 同款默认补齐语义）；
   - `_load_prices_for_factor` 增载 raw `open/suspended/limit_up_price`
     （与 `forward_returns._load_prices` 同构双载）；
   - `rank_ic` / `ic_decay` / `quantile_returns` / `ic_report` 增加 `spec` 参数
     （默认 `LabelSpec(horizon=h)`），输出 attrs 与 md 报告带 `label_spec_hash`；
   - `quantile_returns` 列 `cum_return` 改名 `cum_sum_overlapping_returns`，docstring
     声明"重叠 forward return 的逐日均值累加，仅诊断用，**非可交易净值**"（ADR-0005 §6；
     全仓 grep 确认现无其他使用点）。
3. `src/quant/research/forward_returns.py`：行为不变（现行为即 spec 默认值）；
   `EventStudyResult` 增 `label_spec` 字段，`to_report()` 输出 spec hash。
4. 既有单测中编码旧 off-by-one 语义的期望值随之更新——**每处改动列成清单写入 STATUS
   备注（旧值 → 新值 → 手算依据），清单外断言改动=打回**。

## Non-goals
executable_return（费用/滑点/延期成交标签，M3.5 二批）；不改 `optimize`/`exploratory`
调用语义（默认 spec 生效即可，其文件不在白名单）；HAC/聚类推断（另卡）；不重跑 R1 存档。

## Files to touch
- `src/quant/research/semantics.py`
- `src/quant/research/ic.py`
- `src/quant/research/forward_returns.py`
- `tests/unit/test_semantics.py`
- `tests/unit/test_ic.py`
- `tests/unit/test_forward_returns.py`

## Acceptance criteria
1. 对齐用例（新增，期望值规划者预手算）：12 bar 合成序列
   `close = 100,101,…,111`、`open = close − 0.5`，signal 在 bar0 → h=5 时
   `run_event_study` 与 `_forward_returns` 对同一信号返回**同一数值 106/100.5−1
   = 0.05472636815920395**，且两侧出场日相同；`pytest -q tests/unit/test_semantics.py
   tests/unit/test_ic.py tests/unit/test_forward_returns.py` 全绿。
2. 入场过滤对齐用例：t+1 停牌、t+1 一字涨停（`raw_open >= limit_up_price`）两种构造样本
   在 IC 与事件研究中同样被剔除（IC 有效样本数 = 事件研究 count）；
   `entry_tradability="none"` 时停牌样本不剔除（spec 真实生效，非摆设）。
3. spec hash：同参数两次构造 hash 相同；任一字段变化 hash 变化；`rank_ic(...).attrs`
   与 `ic_report` 输出的 md 含 `label_spec_hash`。
4. 既有断言改动清单在 STATUS 备注逐条列出（旧值 → 新值 → 手算依据）。
5. `pytest -q -m "not integration"` + `ruff check .` + `ruff format --check .` 全绿。

## 验收如何被作弊/退化满足？
1. **凑期望值**：AC1 的 0.05472636815920395 由规划者按 106/100.5−1 预手算写死在卡面，
   off-by-one 实现只能得 0.04477611940298507（105/100.5−1），凑不出来。
2. **借"更新既有断言"夹带无关语义漂移**：AC4 清单 + 审查者逐条手验；清单外断言改动=打回。
3. **过滤只做 suspended 漏 limit_up（F-3 变种：字段没加载所以"没样本可剔"恒绿）**：
   AC2 两种边界分开断言，且用例构造里 `raw_open`/`limit_up_price` 必须真实存在并触发剔除
   （剔除计数 >0 断言，防空转）。
4. **spec 摆设化**（hash 进报告但计算不读 spec）：AC2 的 `entry_tradability="none"` 变体
   断言行为随 spec 变化。
5. **改名不改语义声明**：审查者 diff 核对 docstring 含"非可交易净值"字样。

## 数值验证类别与变形测试
Class A（构造数据逐 bar 手算）。变形测试：h 变化时出场日 = entry_pos + h 逐 h 断言
（h ∈ {1,5}）；spec 字段变化 → hash 变化；entry_tradability 翻转 → 样本集合变化。

## Test plan
新建 `test_semantics.py`（LabelSpec 构造/hash/冻结性）；扩展 `test_ic.py`（对齐 + 过滤 +
attrs hash）与 `test_forward_returns.py`（label_spec 字段 + report 含 hash）。无真实数据依赖。

## Notes / risks
- 本卡后 exploratory/IC 产出与 R1 存档**不可比**（ICIR 等会变）：R1 findings/reviews 冻结
  不重跑，M6/R2 全部用新口径。
- 071 已向量化 ic.py——返工请在向量化实现上做；如向量化路径难以插入过滤，允许在对齐层
  （构建 aligned frame 处）过滤，但性能不得回退到 071 前水平（审查者会抽测耗时）。

# TASK-078: 日度 PIT EligibilityPanel + UniverseProfile（正常股过滤）

- Milestone: M3.5　|　State: ready（新模块，白名单与全部在途卡零交集，可并行）
- Branch: `task/TASK-078-eligibility-panel`　|　Depends: —（数据依赖 staging flags/securities/daily，均已就绪）

## Context
ADR-0005 §P0-3 采纳项 + 用户需求（2026-07-11）：回测前先过滤"正常股票"——非 ST、
上市满 250 交易日、流动性下限等。现状：`list_symbols(at=…)` 只有上市/退市区间过滤，
研究调用 `at=None`；ST/停牌/流动性全靠各模块自行处理。staging 已有全部数据源：
`flags.parquet`（18.37M 行日度 is_st/is_suspended/涨跌停价）、`securities.parquet`
（list/delist_date）、`daily`（amount）。
**方法论红线**：用户例子中的"未来收益完整"被规划者裁定为前视/幸存者偏差，**不得**
作为宇宙条件（见 Non-goals）；退市股必须留在宇宙内直到退市日。

## Goal
一个 (date, symbol) 日度资格面板 + 两档命名 profile：任一研究/回测可用一行调用取得
"t 日可入横截面的正常股票集合"，全部字段只用 ≤t 信息，profile 哈希可进报告。

## Scope
新建 `src/quant/data/eligibility.py`：

```python
@dataclass(frozen=True)
class UniverseProfile:
    name: str
    exclude_boards: frozenset[str] = frozenset({"star", "b"})
    exclude_st: bool = True
    min_ipo_trading_days: int = 250
    min_adv20_amount: float = 3e7          # 元；近20成交日均额
    min_close_price: float = 1.0           # 元；raw 收盘，面值退市风险线

    def profile_hash(self) -> str: ...     # sha256(字段序固定的 canonical repr)[:12]

RESEARCH_V1 = UniverseProfile(name="eligible_research_v1")                      # 3000万档
TRADABLE_V1 = UniverseProfile(name="eligible_tradable_v1", min_adv20_amount=1e8)  # 1亿档

def build_eligibility_panel(
    symbols: Sequence[str], start: str, end: str
) -> pd.DataFrame:
    """index=(date, symbol)；列：board, is_st, is_suspended, ipo_trading_days,
    adv20_amount, close_raw。全部字段仅用 ≤date 的信息。"""

def eligible_mask(panel: pd.DataFrame, profile: UniverseProfile) -> pd.Series: ...
def eligible_symbols(panel: pd.DataFrame, profile: UniverseProfile, date: str) -> list[str]: ...
```

字段口径（逐条，实现必须照此）：
1. `ipo_trading_days`：该 symbol 截至 t 日（含）在 daily 中的**实际 bar 数**累计
   （非自然日）；
2. `adv20_amount`：**最近 20 个有成交 bar**（amount>0 且非停牌）的 amount 均值，窗口
   截止于 t（含 t）；不足 20 个成交 bar → NaN（按不合格处理）；
3. `is_st`/`is_suspended`：flags.parquet 当日值；
4. `close_raw`：原始收盘（非复权）；
5. eligible = 上市中（list_date ≤ t，且 delist_date 缺失或 > t）∧ sec_type=stock
   ∧ board ∉ exclude ∧ (¬is_st 若 exclude_st) ∧ ¬is_suspended
   ∧ ipo_trading_days ≥ 阈 ∧ adv20_amount ≥ 阈 ∧ close_raw ≥ 阈；
6. 数据实现走 staging parquet 直读 + 向量化 groupby/rolling，禁止逐符号 Python 循环
   全市场（AGENTS.md §6）。

## Non-goals
- **禁止任何"未来收益完整/未来仍在市"类条件**——前视 + 幸存者偏差（规划者裁定，
  ADR-0005 §P0-6 同源）；退市股在退市日前必须可入选；
- 不做"临近退市 N 日剔除"（无退市整理期公告数据，用 delist_date 倒推=前视）；
- 不改任何现有调用方（optimize/exploratory/qlib_topk 接线归 TASK-079）；
- 不做行业/市值分层（M3.5 后续）。

## Files to touch
- `src/quant/data/eligibility.py`
- `tests/unit/test_eligibility.py`

## Acceptance criteria
1. 构造 fixture（3~4 symbols × ~40 bar，含：ST 段翻转、停牌段、上市第 249/250 bar 边界、
   adv20 恰好过线/差一档、close 0.99/1.00 边界、中途退市股）：eligible_mask 每格与
   手算表逐位一致；`pytest -q tests/unit/test_eligibility.py` 全绿。
2. **PIT 变形测试**：fixture 尾部追加未来 bar（含把某股未来改成 ST/退市）后，
   `panel.loc[:t]` 与追加前**逐位相同**——任何字段用了未来信息即红。
3. **幸存者变形测试**：中途退市股在退市日前的 eligible 值与"同数据但不退市"版本
   逐位相同（退市事实不得反向影响生前资格）。
4. profile：同参数 hash 稳定、任一字段变化 hash 变化；`RESEARCH_V1`/`TRADABLE_V1`
   仅 `min_adv20_amount` 不同（3e7 vs 1e8）。
5. 真实数据抽查（输出贴 STATUS 备注）：任选 2020-06-30，打印
   `len(eligible_symbols(panel, RESEARCH_V1/TRADABLE_V1, date))` 两档数量与全宇宙数；
   另抽 1 只历史戴帽股，断言其 panel is_st 在 flags.parquet 中对应日期段一致翻转。
6. `pytest -q -m "not integration"` + `ruff check .` + `ruff format --check .` 全绿。

## 验收如何被作弊/退化满足？
1. **恒真面板**（全 eligible）：AC1 fixture 明确含每类不合格样本且逐格手算；AC5 真实
   两档数量必须 < 全宇宙数且 tradable < research（1 亿门槛更严）。
2. **adv20 用居中/未来窗**：AC2 追加未来 bar 变形直接抓。
3. **提前剔除退市股**（幸存者捷径）：AC3 成对对照钉死。
4. **ST 字段读静态表而非日度 flags**：AC5 抽真实戴帽股断言时间段翻转（静态实现给不出
   翻转）。
5. **边界松一档**（≥ 写成 >）：AC1 的 249/250、0.99/1.00、恰好过线样本成对断言。
6. **hash 摆设**：AC4 字段敏感性断言。

## 数值验证类别与变形测试
Class A（构造数据逐格手算）。变形：追加未来 bar 不变（AC2）、退市对照不变（AC3）、
乱序输入 symbols 结果不变（panel 按索引排序输出）。

## Test plan
纯构造 fixture 单测（monkeypatch staging 读取指向 tmp_path parquet）；AC5 为真实数据
本地抽查。

## Notes / risks
- flags 18.37M 行全量 build 的性能目标 < 2 分钟（向量化）；不作硬验收，超了写瓶颈分析；
- adv20 的"成交 bar"定义（amount>0 ∧ 非停牌）会使长停复牌股在复牌初期 adv20 引用
  停牌前旧值——属预期（PIT 下最优可得信息）；
- 面值退市线 1 元对 B 股/北交所语义略异——B 股已被 exclude_boards 排除，北交所留档
  观察；
- 用户原始条件"成交额≥1亿"落在 `TRADABLE_V1`；"未来收益完整"由标签层处理
  （事件研究 exit_missing 显式分桶已有；退市清算语义在 M3.5 二批 executable return 卡）。

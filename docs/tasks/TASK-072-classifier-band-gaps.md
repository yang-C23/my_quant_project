# TASK-072: 数据卫生 — 分类器号段补漏（302/201/395）

- Milestone: M3（数据债，与 032 返工并行）　|　State: ready
- Branch: `task/TASK-072-classifier-band-gaps`　|　Depends: TASK-070（已合并）

## Context
TASK-032 parity 差异分析暴露：`sz302132 中航成飞`（深主板 302 新号段真股票）被 TASK-070 的
兜底分到 `other/other`，被 `list_symbols` 误踢出 universe。审查者随即审计 `sec_type=other`
全部 23 个代码（TASK-032-review 根因 A）：漏网真股票共 2 只——`sz302132`（应 stock/main）、
`sz201872 招港B`（201=深 B 股增发段，应 stock/b）；`sz395xxx` 11 个为深市统计指标代码
（主板Ａ股/总成交等），应归 index。

## Goal
三个号段获得正确分类；再生元数据后 `sz302132` 出现在默认股票 universe，`other` 池不再含
任何有 .tnf 名称的真实证券。

## Scope
1. `staging.py::_classify_security` 增加前缀规则（**禁止符号级枚举**）：
   - `sz` + `302` → `("stock", "main")`；
   - `sz` + `201` → `("stock", "b")`；
   - `sz` + `395` → `("index", "index")`。
   注意插入位置：`302` 必须在现有 `300/301→gem` 之后、兜底之前，避免遮蔽。
2. 再生元数据（唯一允许的 DATA_ROOT 写入）：`myquant etl full --steps securities,flags`。
3. 单测（`tests/unit/test_metadata_staging.py`）：三个号段的分类断言 + 既有用例零改动。

## Non-goals
不改 `list_symbols`；不重跑研究/回测（审查者事后做基线锚点更新）；不清理 12 个在市缺名
占位股（化妆性，留档不修）。

## Files to touch
`src/quant/etl/staging.py`, `tests/unit/test_metadata_staging.py`

## Acceptance criteria
1. `pytest -q tests/unit/test_metadata_staging.py` 全绿（新增三号段用例，既有断言零改动）。
2. 再生后核查（输出贴 STATUS 备注）：
   `python -c "import pandas as pd; from quant.config import get_settings; s=pd.read_parquet(get_settings().staging_dir/'securities.parquet'); print(s[s.symbol.isin(['sz302132','sz201872','sz395001'])][['symbol','sec_type','board']].to_string()); o=s[s.sec_type.eq('other')]; assert o.name.notna().sum()==0, o[o.name.notna()]"`
   —— 期望：302132=stock/main、201872=stock/b、395001=index/index；other 池无带名证券。
3. `python -c "from quant.data.universe import list_symbols; syms=list_symbols(exclude_boards={'star','b'}, at=None); assert 'sz302132' in syms; assert 'sz201872' not in syms; print(len(syms))"`
   —— 302132 进默认 universe（预期 5466），201872 因 b 板被排除。
4. `pytest -q -m "not integration"` + `ruff check .` + `ruff format --check .` 全绿；
   securities 总行数再生前后不变（12169）。

## 验收如何被作弊/退化满足？

1. **符号级枚举**：对 3 个具体代码打补丁而非号段规则——审查者 diff 检查必须是前缀规则。
2. **规则遮蔽**：`302` 若插在 `300/301` 之前不影响（前缀互斥），但 `201` 若插在 `200→b` 之前
   要防 `startswith("20")` 类写法误吞 200 段——用精确三位前缀，新增用例同时断言
   `sz200011` 仍为 b（既有语义不回归）。
3. **只改 parquet 不改代码**：AC2/AC3 读真实 parquet，审查者亲自再生复验（同 070 模式）。
4. **行数变化**：兜底剔行的老路子——AC4 钉死总行数 12169。

## Test plan
纯单测 + 真实元数据再生核查；无新 fixture。

## Notes / risks
- universe 5465→5466（+302132）会改变 `sample_symbols(…,800,42)` 的抽样组成——R1 敏感性
  已在勘误 2 建立稳健性，不再为 +1 股重跑研究；030/034 的基线锚点由**审查者**在本卡合并后
  重跑更新（TASK-030-review 附录二次更新），开发者不做。
- 招港B 归 b 板后 b 计数 165→166、main 3472→3473；写 STATUS 备注时报告五板新计数。

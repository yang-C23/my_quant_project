# TASK-070: 数据卫生 — 证券分类兜底修复（非股票代码混入 universe）

- Milestone: M3（阻塞性数据债）　|　State: ready
- Branch: `task/TASK-070-securities-classify-fix`　|　Depends: TASK-030（已合并）

## Context
TASK-030 审查发现（`docs/reviews/TASK-030-review.md` §重大发现）：`staging.py::_classify_security`
兜底分支把一切未识别前缀归 `("stock", "other")`，导致 258 个 TDX 有 .day 文件但无元数据匹配的
历史代码（sh111xxx 老国债、sh132xxx 可交换债、sz131xxx/sh204xxx 回购、sh520/sh530/sh551/sz184
老基金、sz125/sz180/sz395 等，`name` 全为 None）被标成 `sec_type=stock`，经
`list_symbols(exclude_boards={"star","b"})` 混入研究/回测 universe。回购报价单日可"涨"+68490%，
直接污染 TASK-030 基线（max_drawdown −116%）与 R1 的 800 股样本（39/800）。

## Goal
`list_symbols()` 的默认股票 universe 不再含任何非股票代码；securities.parquet 经既有 CLI 再生后
258 个代码的 `sec_type` 均不再是 `stock`；下游（flags、qlib instruments）口径随之一致。

## Scope
1. `staging.py::_classify_security`：
   - 兜底分支 `return "stock", "other"` 改为 `return "other", "other"`（**积极识别不出股票板别的，
     一律不算股票**——股票前缀白名单已在上方分支穷举：main/gem/star/bse/b）；
   - 顺带补齐可识别的已知前缀（放在兜底之前）：sh111/132 → `("bond","bond")`，
     sz125/126 → `("bond","bond")`，sh204/sz131 → `("repo","other")`，
     sh50x/52x/53x/55x 与 sz18x → `("fund","other")`；识别不了的仍走兜底 `("other","other")`。
2. 用既有 CLI 再生元数据（唯一允许的 DATA_ROOT 写入路径）：
   `myquant etl full --steps securities,flags`（若 flags 不依赖 securities 分类则只跑 securities，
   以 `etl` 命令现有语义为准，卡内不许改 ETL 结构）。
3. 单测（`tests/unit/test_staging.py` 或 `test_metadata_staging.py`）：
   对 Context 列举的每类前缀断言 `_classify_security` 返回值；断言兜底分支 sec_type != "stock"。

## Non-goals
不改 `list_symbols` 签名/语义（它按 sec_type 过滤，源头修正后自然干净）；不重dump qlib bin
（价格数据本身无错，错的是分类）；不做 R1 复跑与 030 基线重跑（审查者职责，见 review 待办）；
不引入新依赖。

## Files to touch
`src/quant/etl/staging.py`, `tests/unit/test_staging.py`, `tests/unit/test_metadata_staging.py`

## Acceptance criteria
1. `pytest -q tests/unit/test_staging.py tests/unit/test_metadata_staging.py`：新增分类用例全绿。
2. 再生后核查（把命令与输出写入 STATUS 备注）：
   `python -c "import pandas as pd; from quant.config import get_settings; s=pd.read_parquet(get_settings().staging_dir/'securities.parquet'); stk=s[s.sec_type.eq('stock')]; print(stk.board.value_counts()); assert stk.name.isna().sum()==0, 'name-less stock remains'"`
   —— 期望：stock 只剩 main/gem/star/bse/b 五板，且无 name=None 的 stock。
3. `python -c "from quant.data.universe import list_symbols; from quant.research.optimize import sample_symbols; import pandas as pd; from quant.config import get_settings; s=pd.read_parquet(get_settings().staging_dir/'securities.parquet').set_index('symbol'); picked=sample_symbols(list_symbols(exclude_boards={'star','b'}, at=None), 800, 42); assert all(s.loc[p,'sec_type']=='stock' for p in picked); print('800-sample clean')"`
4. `pytest -q -m "not integration"` + `ruff check .` + `ruff format --check .` 全绿。

## 验收如何被作弊/退化满足？

1. **只改测试数据不改分类器**：AC2/AC3 读的是 DATA_ROOT 真实 parquet——若手工编辑 parquet 而不改
   `_classify_security`，下次 ETL 再生即回归。审查者将亲自重跑 `etl` 再生并 diff 分类器代码。
2. **兜底改成删除**：把识别不出的代码从 securities 里整行剔除也能让 AC2 过——但会破坏
   `daily` staging 与 securities 的对账（TASK-011 语义：universe 来自 .day 文件枚举）。兜底必须
   **保留行、改 sec_type**，不许减行（AC2 附带断言总行数不变——审查者核对再生前后 `len(s)`）。
3. **过拟合 39 个已知代码**：只对 R1 样本里出现过的 39 个符号打补丁（硬编码列表）——分类必须按
   **前缀规则**写，禁止出现符号级枚举；审查者 diff 检查。
4. **flags 步骤跳过**：securities 再生而 flags 不再生，涨跌停/停牌旗标仍按旧分类的 limit_ratio
   算——AC2 命令跑的是卡面写的完整步骤；若 flags 确不依赖分类，须在 STATUS 备注给出代码级依据。
5. **删除 exclude 的既有语义**：改 `list_symbols` 默认参数或 board 枚举来"顺手清理"= 越 Scope，
   影响全部既有调用方——白名单外文件一律不碰。

## Test plan
纯单测 + 真实元数据再生核查（AC2/AC3）；无需合成 fixture 之外的新数据。

## Notes / risks
- 再生 securities.parquet 后 `securities: main 3472/gem 1433/star 608/bse 560/b 165` 的股票口径
  应与 TASK-011 review 数字一致（回购/债券/基金从 stock 移出，股票五板数字不变）；若有出入，停下
  在 STATUS 备注报告。
- `staging.py:493` 与 `qlib_dump.py` 的 `sec_type=='stock'` 消费点在源头修正后自动收紧——review 时
  审查者会核对 flags 行数变化方向（只减不增）。
- R1 敏感性复跑、030 基线重跑、可能的 findings 勘误由审查者在本卡合并后执行（不在本卡内）。

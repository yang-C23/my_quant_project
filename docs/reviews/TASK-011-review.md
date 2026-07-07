# TASK-011 Review（第 1 轮，规划者审查）

- 日期：2026-07-07　|　审查者：Claude (Fable 5)　|　分支：`task/TASK-011-metadata`（6d6b6c7）
- 开发者自审报告见该分支上的同名文件（合并 v2 时以本文件为准）。

## 验收命令重跑结果（审查者独立运行）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `pytest -q tests/unit/test_metadata_staging.py` | PASS（4 用例） |
| 2 | 全套非集成 + ruff | PASS（40 passed / 全绿） |
| 3 | `myquant etl full --steps meta --no-mirror` | PASS：gbbq 182,295 / securities 12,169 / blocks+holidays 77,405（11.7s）；flags 正确降级等待 basics |

## 实现质量（认可项）

- GBBQ/blocks/holidays 复用 v1 解析器 + staging schema 化，量级与 PG 一致；退市推断（末交易日 < 全局末日−20）识别出 2,895 只退市股——幸存者控制的数据基础成立。
- flags 的涨跌停/ST/停牌合成逻辑与北交所首日豁免正确；`meta` alias 对缺 basics 的优雅降级设计得当。
- gbbq 保留 `category + c1..c4` 原始列（而非卡面预写的命名列）——**接受**，比提前重命名更忠实原始数据；data_platform.md §4 已由规划者同步修订，TASK-012 负责 category=1 的 c1..c4 → fenhong/peigujia/songzhuangu/peigu 映射（对照 v1 `calc_basic.py` 的取列顺序，勿凭猜）。

## 必须修改（CHANGES_REQUESTED）

审查者抽查 securities 分布发现 `stock/other` 桶 4,291 只，其中：

1. **[阻塞] `sz002xxx`（973 只）落入 other**——中小板 2021 年已并入深市主板，必须归 `("stock","main")`。否则宇宙过滤直接丢掉 973 只主板股。
2. **[阻塞] 非股票资产被标 `sec_type="stock"`** 污染宇宙：
   - 可转债 `sh110/113/118`、`sz123/127/128` → `("bond","bond")`（新增枚举）；
   - B股 `sh900`、`sz200` → `("stock","b")`（board 新枚举，宇宙默认排除）；
   - 通达信板块/风格指数 `sh88x`（880/881/887/888 共 ~1,316 只）→ `("index","index")`；
   - 基金补漏：`sh50x/56x/58x`、`sz16x` 已有部分，统一归 `("etf","etf")`（或 fund，二选一并写注释）。
3. `build_flags_staging` 只处理 `sec_type=="stock"` 且 `board != "b"` 的证券（指数/债券/基金无涨跌停语义，B股规则不同，注释声明局限）。
4. 测试：分类表驱动用例覆盖上述全部前缀；新增断言——重建 securities 后 `other` 桶 ≤ 500 且**不含任何 002 开头深市代码**。
5. 重跑 `myquant etl full --steps meta --no-mirror`，在 STATUS 备注贴新分布。

## 结论

**CHANGES_REQUESTED**（修改项 1–5）。修复前先 `git merge v2` 同步分支（评审文件冲突以 v2 版为准）。

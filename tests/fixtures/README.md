# tests/fixtures/ — 测试夹具清单与再生成方法

规则（conventions.md）：单文件 ≤200KB；真实小样本优先；每个 fixture 必须在本文件登记**生成命令**，保证可复现。

## 规划的 fixture 清单（由对应任务卡创建）

| 路径 | 内容 | 生成方法 | 卡 |
|---|---|---|---|
| `tdx/lday/sh600000.day` | 浦发银行日线 200 条真实记录（2021-08-02 起） | `head -c 6400 $TDX_HOME/vipdoc/sh/lday/sh600000.day > sh600000.day` | 010 ✅ |
| `tdx/lday/sz000001.day` | 平安银行 200 条（2021-08-02 起） | 同上（sz 目录） | 010 ✅ |
| `tdx/lday/sz000001_long.day` | 平安银行日线 600 条真实记录（2021-08-02 ~ 2024-01-18） | `head -c 19200 $TDX_HOME/vipdoc/sz/lday/sz000001.day > sz000001_long.day` | 022 |
| `tdx/lday/sh999999.day` | 上证指数 300 条（2021-08-02 ~ 2022-10-28） | `head -c 9600 ...` | 010/023 ✅ |
| `tdx/expected/{symbol}.csv` | 上述三文件的 v1 逐条解析器输出（黄金对照） | v1 `parse_day_file`（commit 326bf99 时点）一次性生成；再生成需 `git show` 取回 v1 实现 | 010 ✅ |
| `tdx/gbbq_sample_decoded.csv` | GBBQ 解码后小样本（category/symbol/date/c1..c4） | 从 v1 `decode_gbbq_file` 输出 schema 手工截取两条代表性记录：category=1 除权、category=5 股本变更；本卡只验证 staging schema 与写盘，不提交加密原始样本 | 011 ✅ |
| `adjust/pg_sz000001_adjust.csv` | PG 黄金复权因子 | `psql "$QUANT_DB_DSN" -c "\copy (select symbol,date,hfq_factor,qfq_factor from tdx.adjust_factor where symbol='sz000001' order by date) to stdout csv header"` | 012 |
| `staging_mini/**` | 迷你 staging（fixture .day 全流程产物） | `tests/fixtures/make_staging_mini.py`（013 编写） | 013 |
| `goldens/bt_legacy_{symbol}.csv` | v1 backtrader 指标黄金值（sma_3_1/sma_40_4/k/d/j/short_trend/long_trend/avghigh/avglow/activity/brick/brick_xg，200 bar 含 warmup NaN） | `python tests/fixtures/generate_goldens.py`（`--check` 校验可复现） | 020 ✅ |
| 各 `*_snapshot.*` | 指标命中日回归快照 | 各指标测试首跑生成 | 022/024 |

## 纪律

- fixture 一经黄金化不许静默更新：更新必须在 commit message 说明原因并同步更新依赖测试。
- 截断的 .day 文件天然合法（32 字节定长记录），但要保证截断点是 32 的整数倍。

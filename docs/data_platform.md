# data_platform.md — 数据平台规范

> 对应 ADR-0002（qlib bin 为唯一研究存储，PG 退役）。ETL 相关任务卡：TASK-010~016。

## 1. 数据根目录（仓库外）

```
/home/yang/quant_data/               # .env: DATA_ROOT
├── tdx_mirror/                      # /mnt/d/new_tdx 的本地镜像（仅 vipdoc + gbbq + 板块文件）
├── staging/                         # Parquet，无损保留 + 衍生，DuckDB 可即席查询
│   ├── daily/exchange=sh|sz|bj/     # part-*.parquet，按 (symbol,date) 排序
│   ├── securities.parquet  gbbq.parquet  blocks.parquet  holidays.parquet
│   ├── basics.parquet  adjust.parquet  flags.parquet
├── qlib/
│   ├── cn_daily/{calendars,instruments,features}/
│   ├── cn_1min/                     # 预留（M5 干跑验证）
│   └── us_daily/                    # M5
└── archive/                         # pg_quant 最终 dump 等归档
```

## 2. 9P/IO 规则（WSL2 强制）与双数据源

- **两个日线源**：`TDX_ZIP`（全历史基线 zip，~12K 文件回溯到 1990）+ `TDX_HOME/vipdoc`（TDX 客户端持续下载的近期数据，约 2021-08 起）。staging 按符号做**并集**，重叠日期 **vipdoc 优先**。
- **全量导入**：`mirror.py` 先把 zip 抽取到 `DATA_ROOT/tdx_mirror/zip_baseline/`（单文件顺序流式读，带 `.complete` 指纹缓存，重跑免抽取），再用 tar 管道批量拷贝 `vipdoc` → `DATA_ROOT/tdx_mirror/vipdoc/`（顺序大块 IO，规避 12K 次随机小读），解析只读镜像。
- **日增量**：不做全量镜像；对每个 `.day` 文件 `seek` 到尾部只读最后 `N×32` 字节（N = 缺失交易日数 + 安全余量 5），直接跨 9P 读也可接受。
- **禁止**并行 worker 直接读 `/mnt/d`（9P + 并发 = 病态性能）。

## 3. TDX .day 二进制格式（沿用 v1 解析器）

每条记录 32 字节小端 `<IIIIIfII>`：date(YYYYMMDD), open, high, low, close（价格 ×100 存储，还原为元）, amount(float, 元), volume(股), reserved。文件名 → 交易所+代码（`sh600000.day`）。解析用 `np.frombuffer` 结构化 dtype 向量化（替代 v1 的逐条 `struct.unpack_from`）。

## 4. staging 表结构（Parquet schema，dtype 必须一致）

### daily（分区 exchange=sh|sz|bj）
| 列 | dtype | 说明 |
|---|---|---|
| symbol | string | `sh600000` 小写规范格式 |
| date | date32 | 交易日 |
| open/high/low/close | float64 | **未复权**原始价（元） |
| volume | int64 | 股 |
| amount | float64 | 元 |

### securities
symbol, name(string), exchange, sec_type(stock/index/etf), board(main/star/gem/bse), list_date, delist_date(nullable) —— 上市/退市区间用于 instruments 的 point-in-time 范围。

### gbbq（股本变迁/除权除息，沿 v1 解码字段）
symbol, date, category(int, 1=除权除息…), fenhong(分红,元/10股), peigujia(配股价), songzhuangu(送转股/10股), peigu(配股/10股), 以及股本类字段(前/后流通股本、总股本, 万股)。

### basics（由 daily+gbbq 向量化衍生）
symbol, date, preclose(理论昨收,考虑除权), pct_chg, amplitude, turnover(%), float_shares, total_shares, float_mktcap(元), total_mktcap(元)。

### adjust
symbol, date, hfq_factor(float64), qfq_factor(float64)。算法：QUANTAXIS 乘法式——除权日 `ratio = preclose_理论 / prev_close_实际`，`hfq_factor` 为累计乘积（首日=1 向后累乘）；`qfq_factor = hfq_factor / hfq_factor_latest`。

### flags
symbol, date, is_suspended(bool, 日历缺口推断), is_st(bool, 名称历史含 ST), limit_up_price, limit_down_price(float64, 按板块/ST 规则预计算), is_limit_up, is_limit_down(bool, close==limit 价)。

### holidays / blocks
沿 v1 语义：交易日历假日表；板块主表 + 成分表（用于"剔除创业板/科创/北证"等 universe 过滤）。

## 5. qlib bin 约定（cn_daily）

- **字段**：`$open $high $low $close $volume` = **hfq 复权后**价格/成交量（qlib CN 惯例），`$factor` = 累计 hfq 因子（`raw = $close / $factor`），另 dump：`$amount $turnover $float_mktcap $total_mktcap $st $suspended $limit_up $limit_down`（0/1 或数值）。
- **calendars/day.txt**：全交易日并集，与 PG `tdx.holidays` 推出的日历交叉核对（M1 gate）。
- **instruments/all.txt**：`SH600000\t上市日\t退市日或末交易日`——point-in-time，杜绝幸存者偏差。另生成子 universe 文件：`nostar.txt`（剔科创）、`main_only.txt` 等。
- **符号**：qlib 侧大写 `SH600000`；仓库内部小写 `sh600000`；互转只经 `quant.data.symbols`。
- **增量**：`update.py` 追加 staging 后用 qlib `DumpDataUpdate` 语义增量追加 bin；**幂等**——连跑两次第二次为无操作。

## 6. 复权公式差异声明（M1 验证必读）

- v2/qlib 采用 **乘法 hfq**（同 v1 `calc_factor.py` 的 hfq 部分）。
- v1 PG 的 **qfq 视图用的是 TDX 减法式**（commit `4b51c91`：`raw*qfq_scale - qfq_offset`），与乘法 qfq 在除权日前的历史段会差几分钱——**这是公式定义差异，不是 bug**。
- 因此 `validate_vs_pg.py` 的判定标准：
  1. 原始 OHLCV：与 PG `daily_kline` **逐值完全相等**（硬失败）；
  2. hfq：因子相对误差 ≤1e-6，hfq 价相对误差 ≤1e-6（硬失败）；
  3. qfq：只做带说明的宽松带（相对误差 ≤0.5% 记 warning，不算失败）；
  4. 日历、instruments 区间、行数：完全一致（硬失败）。

## 7. 美股与分钟线（预留契约）

- **美股（M5, TASK-050）**：yfinance 日线 → 同款 staging schema（exchange=`us`，symbol=`us:AAPL` 内部 / `AAPL` qlib us_daily region）→ `qlib/us_daily`。免费日线够用；后续升级 Polygon/Alpaca 再谈分钟。
- **分钟线（TASK-051 干跑）**：供应商 CSV 契约 = `symbol,datetime,open,high,low,close,volume,amount`；staging 增加 `freq` 维度目录 `staging/min1/`；qlib `cn_1min` 需专用日历（每交易日 240 根，09:31–11:30 / 13:01–15:00 收盘戳）与分钟级 `$factor` 对齐。**用合成 CSV 全流程干跑验证通过后，才允许购买真实数据。**

## 8. CLI 契约

```bash
myquant etl full        # 镜像 + 全量解析 → staging（含 gbbq/securities/blocks/basics/adjust/flags）
myquant dump cn-daily   # staging → qlib/cn_daily （全量重建）
myquant update          # 日增量：tail-read → staging append → qlib 增量 → 幂等
myquant validate        # 调 scripts/validate_vs_pg.py 出对齐报告（M3 后移除）
```

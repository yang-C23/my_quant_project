# 量化回测平台

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 项目定位

- 面向 A 股日线数据的量化回测与指标验证
- 统一数据准备、质量检查、策略回测与报告输出
- 基于 Backtrader 搭建可扩展的策略/指标框架
- **PostgreSQL 数据库存储**：通达信二进制数据导入、GBBQ 解密、自动复权

## 已支持能力

- **数据库存储**：PostgreSQL + `tdx` schema 隔离，28M+ 日线记录
- **通达信数据导入**：.day 二进制解析、GBBQ 股本变迁解密、板块/行业元数据
- **自动复权**：QUANTAXIS 算法计算后复权/前复权因子，视图直接查询
- **增量更新**：从通达信 vipdoc 目录增量同步新日线数据
- 数据下载：Tushare 日线原始价 + 复权因子 (CSV 模式，可选)
- 数据质量检查：异常值、停牌、涨跌停标记
- 指标回测：KDJ 指标 J<0 触发点、双趋势呼吸策略
- 多股票、多时间区间回测
- 自动生成胜率/回报率报告 (1/3/5 天)
- 一键配置化流程 (下载 → 清洗 → 回测)

## 项目结构

```
my_quant_project/
├── configs/
│   ├── pipeline_kdj_j0.yaml      # 配置化流程样例
│   └── pipeline_prepare.yaml     # 数据准备流程
├── quant/
│   ├── backtest/
│   │   ├── engine.py              # Backtrader 回测入口 (支持 DB/CSV)
│   │   └── strategies.py          # 指标/策略逻辑
│   ├── data/
│   │   ├── downloader.py          # Tushare 下载模块
│   │   ├── loader.py              # 数据加载 (DB 优先, CSV 兼容)
│   │   └── quality.py             # 数据清洗与质量检查
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py          # PostgreSQL 连接管理
│   │   └── schema.py              # DDL: 建表、索引、视图
│   ├── indicators/
│   │   ├── kdj.py                 # KDJ 指标
│   │   ├── kdj_tdx.py            # KDJ (通达信兼容)
│   │   ├── dual_trend.py         # 双趋势指标
│   │   └── volume_breath.py      # 量能呼吸指标
│   ├── reporting/
│   │   └── report.py              # 报告生成
│   └── pipeline.py                # 配置驱动流程
├── scripts/
│   ├── import_tdx.py              # 全量导入 (TDX → PostgreSQL)
│   ├── update_daily.py            # 增量更新 (每日同步)
│   ├── tdx_parser.py              # TDX .day 二进制解析
│   ├── gbbq_decoder.py            # GBBQ 加密文件解码
│   ├── blocks_parser.py           # 板块元数据解析
│   ├── calc_basic.py              # 前收盘/换手率/市值计算
│   └── calc_factor.py             # 复权因子计算 (QUANTAXIS)
├── run_pipeline.py                # 配置化流程 CLI
├── run_backtest.py                # 回测 CLI 入口
├── data_downloader.py             # 批量下载日线数据
├── data_quality.py                # 数据质量检查
├── requirements.txt
├── stocklist.csv
└── README.md
```

---

## 数据库架构

### PostgreSQL (Docker)

```bash
# 容器: pg_quant (postgres:16-alpine)
# 连接: host=localhost port=5432 dbname=quant_db user=quant password=quant123
# Schema: tdx
```

### 表结构

| 表/视图 | 说明 | 记录数量级 |
|---------|------|-----------|
| `tdx.securities` | 证券主表（个股/指数/ETF） | ~12K |
| `tdx.daily_kline` | 日K线（统一存储） | ~28M |
| `tdx.gbbq` | 股本变迁 (GBBQ解密) | ~180K |
| `tdx.stocks_basic` | 前收盘/涨跌幅/换手率/市值 | ~28M |
| `tdx.adjust_factor` | 复权因子 (QUANTAXIS算法) | ~28M |
| `tdx.blocks_info` | 板块/指数主表 | ~1K |
| `tdx.blocks_member` | 板块成分股 | ~77K |
| `tdx.holidays` | 假期日历 | ~600 |
| `tdx.v_bfq_daily` | 不复权日线视图 | view |
| `tdx.v_qfq_daily` | 前复权日线视图 | view |
| `tdx.v_hfq_daily` | 后复权日线视图 | view |

---

## 快速开始

### 1. 环境设置

```bash
eval "$(/home/yang/venvs/miniconda3/bin/conda shell.bash hook)"
conda activate /home/yang/venvs/my_quant_env
cd /home/yang/projects/my_quant_project
pip install -r requirements.txt
```

### 2. 启动数据库

```bash
# 首次启动 PostgreSQL 容器
docker run -d --name pg_quant \
  -e POSTGRES_USER=quant -e POSTGRES_PASSWORD=quant123 -e POSTGRES_DB=quant_db \
  -p 5432:5432 -v pgdata_quant:/var/lib/postgresql/data \
  postgres:16-alpine

# 后续启动
docker start pg_quant
```

### 3. 全量导入通达信数据（首次）

```bash
# 从 hsjday.zip 全量导入
python scripts/import_tdx.py \
  --zip /mnt/d/TDX_hsjday.zip \
  --tdxhome /mnt/d/new_tdx

# 或指定单独步骤
python scripts/import_tdx.py --steps init,kline,gbbq,blocks,securities,basic,factor,views
```

### 4. 每日增量更新

```bash
# 先在通达信中下载最新日线数据，然后运行：
python scripts/update_daily.py \
  --vipdoc /mnt/d/new_tdx/vipdoc \
  --tdxhome /mnt/d/new_tdx
```

### 5. SQL 查询示例

```sql
-- 前复权日线
SELECT * FROM tdx.v_qfq_daily WHERE symbol='sz000001' ORDER BY date DESC LIMIT 10;

-- 后复权日线
SELECT * FROM tdx.v_hfq_daily WHERE symbol='sh600519' ORDER BY date DESC LIMIT 10;

-- 查板块成分
SELECT bm.stock_symbol, bi.block_name
FROM tdx.blocks_member bm
JOIN tdx.blocks_info bi ON bm.block_code = bi.block_code
WHERE bm.stock_symbol = 'sz000001';
```

---

## 指标回测

回测引擎默认使用 PostgreSQL 数据源（前复权），也可回退到 CSV 模式。

### KDJ J<0 触发

```bash
python run_backtest.py \
  --data-dir data_clean \
  --start 2015-01-01 \
  --end 2024-12-31 \
  --j-threshold 0 \
  --horizons 1,3,5
```

### Python API (使用数据库)

```python
from quant.data.loader import load_symbol_db, list_symbols_from_db

# 加载前复权日线
df = load_symbol_db('sz000001', start='2024-01-01', adjust='qfq')

# 列出所有股票（排除科创板/北交所）
symbols = list_symbols_from_db(exclude_boards={'star', 'bse'})

# 回测
from quant.backtest.engine import run_kdj_forward_return_backtest
results = run_kdj_forward_return_backtest(
    symbols=['sz000001', 'sh600519'],
    start='2024-01-01', end='2024-12-31',
    source='db',  # 默认即 'db'
)
```

---

## 一键配置化流程

```bash
# 数据准备（下载+清洗，CSV模式）
python run_pipeline.py --config configs/pipeline_prepare.yaml

# KDJ 回测
python run_pipeline.py --config configs/pipeline_kdj_j0.yaml
```

---

## 数据复权算法

复权因子使用 QUANTAXIS 算法，与通达信、雪球、新浪前复权一致：

- 除权日：`ratio = prev_close / preclose_adjusted`，`hfq_factor *= ratio`
- 前复权因子：`qfq_factor = hfq_factor / latest_hfq_factor`
- 前复权价：`adj_price = raw_price * qfq_factor`

---

## 扩展指南

### 新增指标或策略

1. 在 `quant/indicators/` 添加指标实现
2. 在 `quant/backtest/strategies.py` 编写新策略
3. 在 `run_backtest.py` 中新增 CLI 参数

### 新增数据库表

1. 在 `quant/db/schema.py` 添加 DDL
2. 运行 `python scripts/import_tdx.py --steps init`

---

## 下一步规划

- 因子库与特征工程模块
- 回测结果可视化与评分体系
- Walk-forward 验证
- 交易成本与滑点模型
- 分时数据支持 (1min/5min)

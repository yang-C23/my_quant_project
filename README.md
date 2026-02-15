# 量化回测平台

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 🎯 项目定位

- 面向 A 股日线数据的量化回测与指标验证
- 统一数据准备、质量检查、策略回测与报告输出
- 基于 Backtrader 搭建可扩展的策略/指标框架

## ✅ 已支持能力

- 数据下载：Tushare 日线前复权 (qfq)
- 数据质量检查：异常值、停牌、涨跌停标记
- 指标回测：KDJ 指标 J<0 触发点
- 多股票、多时间区间回测
- 自动生成胜率/回报率报告 (1/3/5 天)
- 一键配置化流程 (下载 → 清洗 → 回测)

## 📁 项目结构

```
my_quant_project/
├── configs/
│   └── pipeline_kdj_j0.yaml   # 配置化流程样例
├── quant/
│   ├── backtest/
│   │   ├── engine.py            # Backtrader 回测入口
│   │   └── strategies.py        # 指标/策略逻辑
│   ├── data/
│   │   ├── downloader.py        # Tushare 下载模块
│   │   ├── loader.py            # 数据加载与股票池解析
│   │   └── quality.py           # 数据清洗与质量检查
│   ├── indicators/
│   │   └── kdj.py               # KDJ 指标实现
│   └── reporting/
│       └── report.py            # 报告生成
├── run_pipeline.py             # 配置化流程入口
├── data_downloader.py           # 批量下载日线数据
├── data_quality.py              # 数据质量检查
├── run_backtest.py              # 回测 CLI 入口
├── download_full_history.sh
├── download_indices.sh
├── requirements.txt
├── stocklist.csv
└── README.md
```

---

## 📦 快速开始

### 1. 环境设置

```bash
# 创建环境
conda create -y -p /home/yang/venvs/my_quant_env python=3.10
conda activate /home/yang/venvs/my_quant_env

# 安装依赖
pip install -r requirements.txt
```

### 2. 下载数据

```bash
# 设置 Tushare Token
export TUSHARE_TOKEN="your_token_here"

# 下载完整历史数据（2004-至今）
bash download_full_history.sh
```

### 3. 数据质量检查

```bash
# 单只股票
python data_quality.py data/000001.csv

# 批量检查
python data_quality.py
```

---

## 🧪 指标回测：KDJ J<0 触发

### 示例 1：回测全部股票

```bash
python run_backtest.py \
  --data-dir data \
  --start 2015-01-01 \
  --end 2024-12-31 \
  --j-threshold 0 \
  --horizons 1,3,5
```

### 示例 2：指定股票池

```bash
python run_backtest.py \
  --stocklist stocklist.csv \
  --max-stocks 300 \
  --start 2018-01-01 \
  --end 2024-12-31
```

### 示例 3：手工指定股票列表

```bash
python run_backtest.py \
  --symbols 000001,000002,000333 \
  --start 2019-01-01 \
  --end 2023-12-31
```

### 输出

回测报告默认输出到 `backtest_results/`，包含：

- `*_summary.csv`
- `*_summary.md`

字段含义：

- `signals`: 触发信号数量
- `count`: 有效计算样本数
- `win_rate`: 胜率
- `avg_return`: 平均收益率
- `median_return`: 中位数收益率
- `p25_return/p75_return`: 分位数区间

---

## 🧰 一键配置化流程

使用 `configs/pipeline_kdj_j0.yaml` 进行流程编排：

```bash
python run_pipeline.py --config configs/pipeline_kdj_j0.yaml
```

可配置项包括：

- 数据下载参数（起止日期、复权、线程、板块过滤）
- 数据清洗参数（停牌移除、异常值处理）
- 回测参数（时间区间、KDJ 参数、前瞻天数）

---

## 🧩 扩展指南

### 新增指标或策略

1. 在 `quant/indicators/` 添加指标实现
2. 在 `quant/backtest/strategies.py` 编写新策略
3. 在 `run_backtest.py` 中新增 CLI 参数

### 新增回测类型

你可以扩展：

- 指标回测（如均线交叉、RSI 低位）
- 策略回测（持仓规则 + 资金管理）
- 量化模型（因子打分、机器学习信号）

---

## 📌 下一步规划（可逐步扩展）

- 因子库与特征工程模块
- 回测结果可视化与评分体系
- 策略组合与组合回测
- Walk-forward 验证
- 交易成本与滑点模型

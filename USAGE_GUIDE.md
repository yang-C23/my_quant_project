# 量化交易平台使用指南

## 📋 目录

1. [快速开始](#快速开始)
---

## 🚀 快速开始

### 1. 环境准备

```bash
# 激活虚拟环境
source /home/yang/venvs/my_quant_env/bin/activate

# 进入项目目录
cd /home/yang/projects/my_quant_project
```

### 2. 下载数据

```bash
# 推荐在 /home/yang/tk.csv 保存 token（列名 token）
# 下载脚本会优先读取 tk.csv，也可以使用 --token-file 指定
# 下载全部股票历史数据（2004-至今）
bash download_full_history.sh

# 下载指数数据（基准对比）
bash download_indices.sh
```

### 3. 数据质量检查

```bash
python data_quality.py \
  --data-dir data \
  --output-dir data_clean

如需关闭 adj_price 生成：

```bash
python data_quality.py \
  --data-dir data \
  --output-dir data_clean \
  --no-adj-price
```
```

### 4. 指标回测（KDJ J<0）

```bash
python run_backtest.py \
  --data-dir data_clean \
  --start 2015-01-01 \
  --end 2024-12-31 \
  --j-threshold 0 \
  --horizons 1,3,5
```

### 5. 配置化流程

```bash
python run_pipeline.py --config configs/pipeline_kdj_j0.yaml

建议流程：先做“更新 + 清洗”，再做回测。

仅做“更新 + 清洗”：

```bash
python run_pipeline.py --config configs/pipeline_prepare.yaml
```
```

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
# 下载全部股票历史数据（2004-2025）
bash download_full_history.sh

# 下载指数数据（基准对比）
bash download_indices.sh
```

### 3. 数据质量检查

```bash
# 检查单只股票数据质量
python data_quality.py data/000001.csv

# 批量检查
python data_quality.py
```

# 量化交易平台

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 🎯 项目特点

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
# 设置Tushare Token
export TUSHARE_TOKEN="your_token_here"

# 下载完整历史数据（2004-2025）
bash download_full_history.sh
```

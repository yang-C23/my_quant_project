#!/bin/bash
#
# 下载完整历史数据（2004-2025）
# 
# 使用方法：
#   export TUSHARE_TOKEN="your_token"
#   bash download_full_history.sh
#

set -e

echo "=========================================="
echo "下载完整历史数据 (2004-01-01 至今)"
echo "=========================================="
echo ""

# 检查环境变量
if [ -z "$TUSHARE_TOKEN" ]; then
    echo "错误: 未设置 TUSHARE_TOKEN 环境变量"
    echo "请运行: export TUSHARE_TOKEN='your_token'"
    exit 1
fi

# 激活conda环境
# conda activate /home/yang/venvs/my_quant_env

# 运行下载脚本（添加--overwrite强制重新下载）
python data_downloader.py \
    --stocklist stocklist.csv \
    --start 20040101 \
    --end today \
    --adjust qfq \
    --workers 5 \
    --overwrite \
    --out data

echo ""
echo "=========================================="
echo "下载完成！"
echo "数据保存在: ./data/"
echo "日志文件: ./download.log"
echo "=========================================="


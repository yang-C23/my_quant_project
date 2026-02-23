#!/bin/bash
# 下载指数数据用于基准对比

echo "========================================"
echo "下载指数数据（沪深300、中证1000）"
echo "========================================"

# 检查环境变量，若为空则尝试读取 tk.csv
if [ -z "$TUSHARE_TOKEN" ]; then
    if [ -f "/home/yang/tk.csv" ]; then
        export TUSHARE_TOKEN=$(/home/yang/venvs/my_quant_env/bin/python - <<'PY'
import pandas as pd
print(pd.read_csv('/home/yang/tk.csv')['token'].iloc[0])
PY
)
    fi
fi

if [ -z "$TUSHARE_TOKEN" ]; then
    echo "错误: 未设置 TUSHARE_TOKEN 且未找到 /home/yang/tk.csv"
    exit 1
fi

# 创建临时的指数列表文件
cat > /tmp/indices.csv << EOF
ts_code,name,industry
000300.SH,沪深300,指数
000852.SH,中证1000,指数
000001.SH,上证指数,指数
399001.SZ,深证成指,指数
399006.SZ,创业板指,指数
EOF

# 使用data_downloader下载指数数据
/home/yang/venvs/my_quant_env/bin/python data_downloader.py \
    --stocklist /tmp/indices.csv \
    --start 20040101 \
    --end today \
    --workers 1 \
    --overwrite \
    --out data

echo "========================================"
echo "指数数据下载完成！"
echo "========================================"

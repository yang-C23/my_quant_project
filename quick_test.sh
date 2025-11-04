#!/bin/bash
# 快速测试脚本
# 用法: bash quick_test.sh

echo "========================================"
echo "量化平台快速测试"
echo "========================================"

# 1. 检查数据
echo -e "\n[1/5] 检查数据文件..."
DATA_COUNT=$(ls data/*.csv 2>/dev/null | wc -l)
echo "数据文件数: $DATA_COUNT"

if [ $DATA_COUNT -lt 10 ]; then
    echo "警告: 数据文件较少，建议运行 bash download_full_history.sh"
fi

# 2. 单票回测测试
echo -e "\n[2/5] 单票回测测试（3只股票）..."
/home/yang/venvs/my_quant_env/bin/python test_dual_line_strategy.py 2>&1 | tail -20

# 3. 参数优化测试
echo -e "\n[3/5] 跳过参数优化（耗时较长，如需运行请手动执行: python strategy_optimizer.py）"

# 4. 数据质量检查
echo -e "\n[4/5] 数据质量检查..."
/home/yang/venvs/my_quant_env/bin/python -c "
import pandas as pd
from pathlib import Path
import sys

data_dir = Path('data')
csv_files = list(data_dir.glob('*.csv'))

print(f'总文件数: {len(csv_files)}')

# 抽样检查
sample_size = min(10, len(csv_files))
issues = []

for csv_file in csv_files[:sample_size]:
    try:
        df = pd.read_csv(csv_file)
        if len(df) < 100:
            issues.append((csv_file.name, len(df)))
    except Exception as e:
        issues.append((csv_file.name, str(e)))

if issues:
    print(f'\n发现问题:')
    for name, issue in issues:
        print(f'  - {name}: {issue}')
else:
    print('抽样检查通过！')
" 2>&1

# 5. 环境检查
echo -e "\n[5/5] 环境检查..."
/home/yang/venvs/my_quant_env/bin/python -c "
import sys
print(f'Python版本: {sys.version.split()[0]}')

# 检查关键库
packages = ['pandas', 'numpy', 'backtrader', 'lightgbm', 'sklearn']
for pkg in packages:
    try:
        mod = __import__(pkg)
        version = getattr(mod, '__version__', 'unknown')
        print(f'{pkg}: {version}')
    except ImportError:
        print(f'{pkg}: 未安装')

# 检查GPU
try:
    import lightgbm as lgb
    # 简单测试GPU是否可用
    print('LightGBM GPU支持: 需运行训练测试')
except:
    print('LightGBM GPU支持: 未知')
"

echo -e "\n========================================"
echo "测试完成！"
echo "========================================"
echo -e "\n下一步建议:"
echo "1. 运行组合回测: python portfolio_backtest.py stocklist.csv"
echo "2. 计算因子: python feature_engineering.py 000001"
echo "3. 查看详细指南: cat USAGE_GUIDE.md"
echo ""


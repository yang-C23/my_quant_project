#!/bin/bash
# 完整工作流程脚本
# 从零开始运行整个量化交易平台

echo "=========================================="
echo "量化交易平台 - 完整工作流程"
echo "=========================================="

# 设置错误时退出
set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 函数：打印步骤
print_step() {
    echo -e "\n${GREEN}[步骤 $1]${NC} $2"
}

# 函数：打印警告
print_warning() {
    echo -e "${YELLOW}[警告]${NC} $1"
}

# 函数：打印错误
print_error() {
    echo -e "${RED}[错误]${NC} $1"
}

# 激活虚拟环境
VENV_PATH="/home/yang/venvs/my_quant_env"
if [ -d "$VENV_PATH" ]; then
    source "$VENV_PATH/bin/activate"
    print_step "0" "虚拟环境已激活"
else
    print_error "虚拟环境不存在: $VENV_PATH"
    exit 1
fi

# 进入项目目录
cd /home/yang/projects/my_quant_project

# ========================================
# 阶段1: 环境检查
# ========================================
print_step "1" "环境检查"

python -c "
import sys
import importlib

packages = ['pandas', 'numpy', 'backtrader', 'sklearn']
missing = []

for pkg in packages:
    try:
        importlib.import_module(pkg)
        print(f'✓ {pkg}')
    except ImportError:
        missing.append(pkg)
        print(f'✗ {pkg} (缺失)')

if missing:
    print(f'\n需要安装: {\" \".join(missing)}')
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    print_error "环境检查失败"
    exit 1
fi

# ========================================
# 阶段2: 数据准备（可选，如果数据已存在则跳过）
# ========================================
print_step "2" "数据准备"

DATA_COUNT=$(ls data/*.csv 2>/dev/null | wc -l)
echo "当前数据文件数: $DATA_COUNT"

if [ $DATA_COUNT -lt 100 ]; then
    print_warning "数据文件较少，是否下载？(y/n)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        bash download_full_history.sh
        bash download_indices.sh
    fi
else
    echo "数据文件充足，跳过下载"
fi

# ========================================
# 阶段3: 数据质量检查
# ========================================
print_step "3" "数据质量检查"

python data_quality.py data/000001.csv 2>&1 | tail -10
python data_quality.py data/000002.csv 2>&1 | tail -10
python data_quality.py data/002594.csv 2>&1 | tail -10

# ========================================
# 阶段4: 单票回测测试
# ========================================
print_step "4" "单票回测测试（3只股票）"

python test_dual_line_strategy.py 2>&1 | tee logs/test_single_stock.log

echo ""
echo "回测结果保存在: backtest_results/"
ls -lh backtest_results/*_dual_line_metrics.json 2>/dev/null | tail -3

# ========================================
# 阶段5: 条件消融实验（可选）
# ========================================
print_step "5" "条件消融实验（可选，耗时约10分钟）"

echo "是否运行条件消融实验？(y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    python condition_ablation_test.py 2>&1 | tee logs/condition_ablation.log
    
    if [ -f "backtest_results/condition_ablation/condition_combinations.csv" ]; then
        echo ""
        echo "条件组合结果（Top 5）:"
        head -6 backtest_results/condition_ablation/condition_combinations.csv
    fi
fi

# ========================================
# 阶段6: 参数优化（可选）
# ========================================
print_step "6" "参数优化（可选，耗时约5分钟）"

echo "是否运行参数优化？(y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    python strategy_optimizer.py 2>&1 | tee logs/parameter_optimization.log
fi

# ========================================
# 阶段7: 全市场回测（可选）
# ========================================
print_step "7" "全市场回测（可选，耗时较长）"

echo "是否运行全市场回测？(y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    python run_full_market_backtest.py \
        --stocklist stocklist.csv \
        --start-date 2020-01-01 \
        --end-date 2024-12-31 \
        --j-threshold 15.0 \
        --volume-ratio 2.5 \
        2>&1 | tee logs/full_market_backtest.log
fi

# ========================================
# 阶段8: 因子计算（可选）
# ========================================
print_step "8" "因子计算（可选）"

echo "是否计算因子？(y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    echo "计算000001的因子..."
    python feature_engineering.py 000001 2>&1 | tail -20
fi

# ========================================
# 阶段9: ML模型训练（可选，需要先安装LightGBM）
# ========================================
print_step "9" "ML模型训练（可选）"

# 检查LightGBM是否安装
python -c "import lightgbm" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "LightGBM已安装"
    echo "是否训练ML模型？(y/n)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        python -c "
from feature_engineering import FeatureEngineer
from ml_trainer import LightGBMTrainer

print('构建训练数据集...')
engineer = FeatureEngineer()
X, y = engineer.build_multi_stock_dataset(
    stock_list=['000001', '000002', '002594'],
    save_path='ml_data_test'
)

print('训练模型...')
trainer = LightGBMTrainer(use_gpu=False)  # 改为False避免GPU问题
trainer.train(X, y)
trainer.save_model('models/lgbm_quick.txt')
print('模型已保存到: models/lgbm_quick.txt')
        " 2>&1 | tee logs/ml_training.log
    fi
else
    print_warning "LightGBM未安装，跳过ML训练"
    echo "如需安装，运行: bash install_ml_dependencies.sh"
fi

# ========================================
# 总结
# ========================================
echo ""
echo "=========================================="
echo "工作流程完成！"
echo "=========================================="

echo ""
echo "📊 生成的结果:"
echo "  - 单票回测: backtest_results/*_dual_line_metrics.json"
[ -f "backtest_results/condition_ablation/condition_combinations.csv" ] && echo "  - 条件消融: backtest_results/condition_ablation/"
[ -f "logs/parameter_optimization.log" ] && echo "  - 参数优化: logs/parameter_optimization.log"
[ -f "logs/full_market_backtest.log" ] && echo "  - 全市场回测: logs/full_market_backtest.log"
[ -d "ml_data_test" ] && echo "  - ML数据集: ml_data_test/"
[ -f "models/lgbm_quick.txt" ] && echo "  - ML模型: models/lgbm_quick.txt"

echo ""
echo "📚 下一步建议:"
echo "  1. 查看回测结果: cat backtest_results/002594_dual_line_metrics.json"
echo "  2. 阅读使用指南: cat FILE_GUIDE.md"
echo "  3. 查看项目状态: cat FINAL_STATUS.md"

echo ""
echo "✅ 完成！"


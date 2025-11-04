#!/bin/bash
# 安装机器学习相关依赖
# 用法: bash install_ml_dependencies.sh

echo "========================================"
echo "安装ML相关依赖"
echo "========================================"

# 激活虚拟环境
source /home/yang/venvs/my_quant_env/bin/activate || {
    echo "错误: 无法激活虚拟环境"
    exit 1
}

echo -e "\n[1/3] 安装LightGBM..."
pip install lightgbm

echo -e "\n[2/3] 安装SHAP（可选，用于特征重要性分析）..."
pip install shap

echo -e "\n[3/3] 安装其他ML工具..."
pip install scikit-optimize  # 贝叶斯优化

echo -e "\n========================================"
echo "安装完成！"
echo "========================================"

# 测试安装
echo -e "\n测试LightGBM安装..."
python -c "
import lightgbm as lgb
print(f'LightGBM版本: {lgb.__version__}')

# 测试GPU支持
try:
    import lightgbm as lgb
    # 创建一个简单数据集测试
    import numpy as np
    X = np.random.rand(100, 10)
    y = np.random.randint(0, 2, 100)
    
    train_data = lgb.Dataset(X, label=y)
    params = {'device': 'gpu', 'verbose': -1}
    
    # 尝试训练（如果GPU不可用会自动回退到CPU）
    model = lgb.train(params, train_data, num_boost_round=10)
    print('GPU支持: 可用（或已回退到CPU）')
except Exception as e:
    print(f'GPU测试失败: {e}')
    print('提示: 如需GPU支持，请安装: pip install lightgbm --install-option=--gpu')
"

echo -e "\n如需GPU加速，请运行:"
echo "pip install lightgbm --install-option=--gpu --install-option='--opencl-include-dir=/usr/local/cuda/include/' --install-option='--opencl-library=/usr/local/cuda/lib64/libOpenCL.so'"


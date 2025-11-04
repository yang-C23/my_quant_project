# 量化交易平台使用指南

## 📋 目录

1. [快速开始](#快速开始)
2. [规则策略回测](#规则策略回测)
3. [因子分析流程](#因子分析流程)
4. [机器学习策略](#机器学习策略)
5. [组合回测](#组合回测)
6. [参数优化](#参数优化)
7. [常见问题](#常见问题)

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

---

## 📈 规则策略回测

### 1. 单票回测测试

测试规则策略在3只代表性股票上的表现：

```bash
python test_dual_line_strategy.py
```

**测试股票：**
- 000001 (平安银行) - 低波动
- 000002 (万科A) - 中等波动
- 002594 (比亚迪) - 高波动

### 2. 单票详细回测

```bash
python rule_strategy_backtest.py \
    --symbol 000001 \
    --start-date 2020-01-01 \
    --end-date 2024-12-31 \
    --initial-cash 100000 \
    --white-period 10 \
    --j-threshold 13 \
    --volume-ratio 3.5
```

**关键参数：**
- `--symbol`: 股票代码
- `--white-period`: 白线周期（默认10）
- `--j-threshold`: J值超卖阈值（默认13）
- `--volume-ratio`: 成交量呼吸度阈值（默认3.5）

### 3. 参数优化

寻找最优参数组合：

```bash
python strategy_optimizer.py
```

优化参数范围：
- `j_threshold`: [5, 10, 13, 15, 20]
- `volume_ratio_threshold`: [2.0, 2.5, 3.0, 3.5, 4.0]

---

## 🔬 因子分析流程

### 1. 计算因子

```bash
# 为单只股票计算所有因子（55个）
python feature_engineering.py 000001
```

**因子分类：**
- 自定义因子（10个）：趋势、价格位置、KDJ、成交量呼吸度等
- Alpha101因子（30个）：动量、量价、反转类
- 技术因子（10个）：RSI、MACD、布林带、ATR等
- 行业因子（5个）：行业动量、排名、中性化、波动率、相关性

### 2. IC分析

评估因子的预测能力：

```bash
python -c "
from factor_lib.ic_analysis import ICAnalyzer
import pandas as pd

# 加载特征数据
X = pd.read_csv('features.csv')
y = pd.read_csv('labels.csv')

# IC分析
analyzer = ICAnalyzer()
ic_df = analyzer.calculate_ic(X, y, forward_periods=[5, 10, 20])
print(ic_df.head(20))

# 可视化
analyzer.plot_ic_series(ic_df, 'ic_analysis.png')
"
```

**关键指标：**
- **IC（Information Coefficient）**: 因子与未来收益的相关性
- **IR（Information Ratio）**: IC均值/IC标准差，衡量稳定性
- **IC > 0.05**: 有效因子
- **IR > 0.5**: 优质因子

### 3. 因子预处理

```python
from factor_lib.preprocessing import FactorPreprocessor

preprocessor = FactorPreprocessor(
    winsorize_method='quantile',
    fill_method='forward',
    standardize_method='zscore'
)

# 预处理因子
X_processed = preprocessor.fit_transform(X)
```

---

## 🤖 机器学习策略

### 1. 特征工程

```python
from feature_engineering import FeatureEngineer

# 初始化
engineer = FeatureEngineer(
    data_dir="data",
    industry_mapping_file="stocklist.csv",
    use_preprocessing=True
)

# 构建多股票数据集
X, y = engineer.build_multi_stock_dataset(
    stock_list=['000001', '000002', '002594'],
    label_type='triple_barrier',
    label_params={
        'profit_take': 0.10,    # 10%止盈
        'stop_loss': 0.05,       # 5%止损
        'time_limit': 10         # 10天时间限制
    },
    save_path='ml_data'
)
```

**标签分布：**
- `1`: 买入信号（先触及止盈）
- `-1`: 卖出信号（先触及止损）
- `0`: 中性（超时未触及）

### 2. 模型训练

```python
from ml_trainer import LightGBMTrainer, time_series_cv_train
import pandas as pd

# 加载数据
X = pd.read_csv('ml_data/features.csv')
y = pd.read_csv('ml_data/labels.csv')

# 时间序列交叉验证训练
trainer, cv_results = time_series_cv_train(
    X, y,
    n_splits=5,
    trainer_params={
        'task_type': 'classification',
        'use_gpu': True,
        'random_state': 42
    },
    train_params={
        'num_boost_round': 1000,
        'early_stopping_rounds': 50
    },
    save_dir='models/lgbm_cv'
)

# 保存最终模型
trainer.save_model('models/lgbm_final.txt')

# 特征重要性分析
trainer.plot_feature_importance(top_n=20, save_path='models/feature_importance.png')

# SHAP分析
trainer.shap_analysis(X.sample(500), save_dir='models/shap')
```

**GPU加速参数：**
```python
params = {
    'device': 'gpu',
    'gpu_platform_id': 0,
    'gpu_device_id': 0,
    'num_leaves': 31,
    'learning_rate': 0.05
}
```

### 3. 模型评估

```python
# 在测试集上评估
metrics = trainer.evaluate(X_test, y_test, save_dir='models/evaluation')

print(f"准确率: {metrics['accuracy']:.4f}")
print(f"F1分数: {metrics['f1']:.4f}")
```

---

## 📊 组合回测

### 1. 规则策略组合回测

```bash
python portfolio_backtest.py stocklist.csv
```

或者使用Python API：

```python
from portfolio_backtest import run_portfolio_backtest
from custom_strategies.dual_line_breath import DualLineBreathStrategy
from datetime import datetime

result = run_portfolio_backtest(
    stock_list_file="stocklist.csv",
    strategy_class=DualLineBreathStrategy,
    strategy_params={
        'printlog': False,
        'white_period': 10,
        'j_threshold': 15,           # 使用优化后的参数
        'volume_ratio_threshold': 2.5
    },
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2024, 12, 31),
    initial_cash=1000000.0,
    max_positions=10,
    save_results=True,
    plot_results=True
)

print(f"总收益率: {result.total_return_pct:.2f}%")
print(f"夏普比率: {result.sharpe_ratio:.4f}")
print(f"最大回撤: {result.max_drawdown_pct:.2f}%")
```

### 2. ML策略组合回测

```python
from portfolio_backtest import run_portfolio_backtest
from custom_strategies.ml_strategy import MLSignalStrategy
from datetime import datetime

result = run_portfolio_backtest(
    stock_list_file="stocklist.csv",
    strategy_class=MLSignalStrategy,
    strategy_params={
        'model_path': 'models/lgbm_final.txt',
        'top_n': 10,
        'position_size': 0.10,
        'rebalance_freq': 'weekly',
        'use_rule_filter': True,
        'min_trend_strength': 0.0,
        'min_volume_breath': 2.0,
        'printlog': False
    },
    fromdate=datetime(2023, 1, 1),
    todate=datetime(2024, 12, 31),
    initial_cash=1000000.0,
    max_positions=10
)
```

**调仓频率：**
- `'daily'`: 每日调仓
- `'weekly'`: 每周一调仓（推荐）
- `'monthly'`: 每月初调仓

---

## ⚙️ 参数优化

### 1. 网格搜索

```python
from strategy_optimizer import StrategyOptimizer
from custom_strategies.dual_line_breath import DualLineBreathStrategy

optimizer = StrategyOptimizer(
    strategy_class=DualLineBreathStrategy,
    stock_list=['000001', '000002', '002594'],
    data_dir='data'
)

# 定义参数空间
param_grid = {
    'j_threshold': [5, 10, 13, 15, 20],
    'volume_ratio_threshold': [2.0, 2.5, 3.0, 3.5, 4.0]
}

# 优化
best_params, results_df = optimizer.grid_search(
    param_grid,
    objective='sharpe_ratio',  # 优化目标：sharpe_ratio, total_return, etc.
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2024, 12, 31)
)

print(f"最优参数: {best_params}")
print(f"\nTop 5组合:")
print(results_df.head())
```

### 2. 贝叶斯优化

```python
from skopt import BayesSearchCV
from skopt.space import Real, Integer

# 定义搜索空间
search_space = {
    'j_threshold': Integer(5, 25),
    'volume_ratio_threshold': Real(1.5, 5.0),
    'white_period': Integer(5, 20)
}

# 贝叶斯优化
optimizer = BayesSearchCV(
    estimator=...,
    search_spaces=search_space,
    n_iter=50,
    cv=5,
    n_jobs=-1,
    random_state=42
)
```

---

## ❓ 常见问题

### Q1: 如何处理数据不足的问题？

**A:** 检查数据下载是否完整：

```bash
# 重新下载（覆盖模式）
python data_downloader.py \
    --stocklist stocklist.csv \
    --start 20040101 \
    --end today \
    --adjust qfq \
    --overwrite \
    --out data
```

### Q2: 回测中交易次数为0怎么办？

**A:** 策略条件过于严格，尝试：
1. 降低J值阈值：`j_threshold=20`
2. 降低成交量呼吸度阈值：`volume_ratio_threshold=2.0`
3. 扩大股票池
4. 检查数据质量

### Q3: 如何使用GPU加速？

**A:** 确保安装了支持GPU的LightGBM：

```bash
# 安装GPU版本LightGBM
pip install lightgbm --install-option=--gpu

# 在训练时设置use_gpu=True
trainer = LightGBMTrainer(
    task_type='classification',
    use_gpu=True
)
```

### Q4: 因子计算太慢怎么办？

**A:** 使用多进程加速：

```python
from multiprocessing import Pool

def calculate_factors_parallel(stock_codes):
    with Pool(processes=8) as pool:
        results = pool.map(engineer.calculate_all_factors, stock_codes)
    return results
```

### Q5: 如何添加自定义因子？

**A:** 在`factor_lib/custom_factors.py`中添加：

```python
class MyCustomFactor(FactorBase):
    def __init__(self, window: int = 20):
        self.window = window
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        # 实现你的因子逻辑
        return data['close'].pct_change(self.window)
```

### Q6: 模型过拟合怎么办？

**A:** 
1. 使用时间序列交叉验证
2. 增加正则化：`lambda_l1=0.5, lambda_l2=0.5`
3. 减少特征数量（特征选择）
4. 增加训练数据
5. Early Stopping

### Q7: 如何对比策略表现？

**A:** 

```python
# 对比多个策略
strategies = [
    ('Rule_J13', DualLineBreathStrategy, {'j_threshold': 13}),
    ('Rule_J15', DualLineBreathStrategy, {'j_threshold': 15}),
    ('ML', MLSignalStrategy, {'model_path': 'models/lgbm_final.txt'})
]

results = []
for name, strategy_class, params in strategies:
    result = run_portfolio_backtest(
        stock_list_file="stocklist.csv",
        strategy_class=strategy_class,
        strategy_params=params,
        ...
    )
    results.append((name, result))

# 对比分析
comparison_df = pd.DataFrame([
    {
        'strategy': name,
        'return': r.total_return_pct,
        'sharpe': r.sharpe_ratio,
        'max_dd': r.max_drawdown_pct,
        'trades': r.total_trades
    }
    for name, r in results
])

print(comparison_df)
```

---

## 📚 进阶主题

### 1. 市场状态过滤器

```python
# 添加大盘趋势判断
def is_bull_market(index_data):
    """判断是否为牛市"""
    ma_20 = index_data['close'].rolling(20).mean()
    ma_60 = index_data['close'].rolling(60).mean()
    return (ma_20.iloc[-1] > ma_60.iloc[-1])

# 在策略中使用
if is_bull_market(index_data):
    # 激进参数
    self.params.j_threshold = 20
else:
    # 保守参数
    self.params.j_threshold = 10
```

### 2. 动态仓位管理

```python
def calculate_position_size(signal_strength, volatility):
    """基于信号强度和波动率的动态仓位"""
    base_size = 0.10
    signal_adj = signal_strength / 100  # 归一化
    vol_adj = 1.0 / (1.0 + volatility)  # 高波动降低仓位
    return base_size * signal_adj * vol_adj
```

### 3. 风险预算

```python
# Kelly公式
def kelly_criterion(win_rate, avg_win, avg_loss):
    """凯利公式计算最优仓位"""
    if avg_loss == 0:
        return 0
    return win_rate - ((1 - win_rate) / (avg_win / avg_loss))
```

---

## 📞 支持与反馈

如有问题，请检查：
1. `README.md` - 项目总体说明
2. `QUICK_START.md` - 快速入门
3. `IMPLEMENTATION_STATUS.md` - 实现状态
4. 各模块的docstring和注释

祝量化交易成功！🚀


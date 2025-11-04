# 快速开始指南

## 🚀 立即开始的5个步骤

### 步骤1: 下载完整数据（重要！）

```bash
cd /home/yang/projects/my_quant_project

# 确保Token已设置
export TUSHARE_TOKEN="your_token_here"

# 运行下载脚本（已添加--overwrite，会重新下载）
bash download_full_history.sh
```

**预计时间**: 2-4小时（取决于网络和Tushare账户权限）  
**数据量**: 5000+只股票 × 20年数据

---

### 步骤2: 数据质量检查

```bash
python data_quality.py
```

这将检查：
- 停牌日数量
- 涨跌停分布
- 异常值数量
- 数据完整性

---

### 步骤3: 单票回测（测试策略）

```bash
# 测试单只股票
python rule_strategy_backtest.py --symbol 000001

# 或运行多只测试
python test_dual_line_strategy.py
```

**查看结果**:
- `backtest_results/xxx_metrics.json` - 回测指标
- `backtest_results/xxx_vs_index.png` - 收益曲线图

---

### 步骤4: 参数优化

```bash
# 方法1：直接运行优化脚本
python strategy_optimizer.py

# 方法2：在Python中
from strategy_optimizer import StrategyOptimizer
from custom_strategies.dual_line_breath import DualLineBreathStrategy

optimizer = StrategyOptimizer(strategy_cls=DualLineBreathStrategy)

# 网格搜索
best_params, results_df = optimizer.grid_search(
    param_grid={
        'j_threshold': [5, 10, 13, 15, 20],
        'volume_ratio_threshold': [2.5, 3.0, 3.5, 4.0, 4.5],
    },
    symbols=['000001', '000002', '000651', '600519', '002594'],  # 5只不同风格股票
    objective='sharpe',
    min_trades=3  # 至少3笔交易
)

print("最优参数:", best_params)
print("\n前10组合:")
print(results_df.head(10))
```

---

### 步骤5: 因子分析（为ML准备）

```python
from factor_lib.base import FactorEngine
from factor_lib.custom_factors import *
from factor_lib.ic_analysis import FactorAnalyzer

# 创建因子引擎
engine = FactorEngine(data_dir='data', cache_dir='factor_cache')

# 加载数据
engine.load_data(
    symbols=['000001', '000002', '600519', '000651', '002594'],
    start_date='2020-01-01',
    end_date='2024-12-31'
)

# 注册因子
factors = [
    TrendSpreadFactor(short_period=10),
    PriceZoneFactor(short_period=10),
    VolumeBreathRatioFactor(period=30),
    PriceVolumeCorrelationFactor(period=20),
]

for factor in factors:
    engine.register_factor(factor)

# 计算
results = engine.compute_all()

# IC分析
analyzer = FactorAnalyzer(output_dir='factor_analysis')
for factor_name, factor_result in results.items():
    report = analyzer.generate_report(
        factor_name=factor_name,
        factor_panel=factor_result.data,
        price_panel=price_df,  # 需要准备价格数据
        periods=[5, 10, 20]
    )
    print(f"{factor_name} - IC均值: {report['ic_stats'][5]['IC_mean']:.4f}")
```

---

## 🎯 重要提示

### 1. 关于收盘价

**问**: 为什么用收盘价而不是开盘价或其他价格？

**答**: 
- ✅ **噪声更少**: 收盘价是全天交易后的共识价格
- ✅ **流动性更好**: A股有收盘集合竞价（14:57-15:00）
- ✅ **可复现**: 业界标准，便于对比
- ✅ **实盘可行**: 收盘计算信号，次日开盘执行（T+1）

**我们的项目**: 所有因子计算和策略信号都基于收盘价 ✅

---

### 2. 关于交易次数少

**如果测试发现交易次数很少（<5笔/年）**:

**原因分析**:
1. 4个买入条件同时满足概率低
2. 2024年数据时间太短
3. 市场环境不适合（震荡下跌）

**解决方案**:

#### 方案A: 参数优化（推荐）
```python
# 放宽条件
best_params = {
    'j_threshold': 15,  # 从13提高到15
    'volume_ratio_threshold': 3.0,  # 从3.5降低到3.0
    'position_pct': 0.10
}
```

#### 方案B: 动态阈值（K-means）
```python
from strategy_optimizer import StrategyOptimizer

optimizer = StrategyOptimizer(strategy_cls=DualLineBreathStrategy)

# 计算动态J阈值
j_threshold = optimizer.compute_dynamic_j_threshold(
    j_values=kdj_j_series,  # 从历史数据提取
    method='kmeans',
    n_clusters=3
)
```

#### 方案C: 股票池策略（最推荐）
```python
# 不是针对单只股票，而是每日从股票池筛选
# 每天筛选满足条件的前N只买入

from portfolio_backtest import PortfolioBacktest

portfolio = PortfolioBacktest(
    strategy_cls=DualLineBreathStrategy,
    stock_pool=all_stocks,  # 全部5000+只股票
    max_positions=10,       # 最多持有10只
    daily_select_top_n=20,  # 每日筛选前20只
)

result = portfolio.run(start_date='2020-01-01')
```

#### 方案D: 市场过滤器
```python
from strategy_optimizer import MarketRegimeDetector

# 根据大盘环境动态调整
detector = MarketRegimeDetector(index_symbol='000001')  # 上证指数
regime = detector.detect_regime(index_data)

if regime == 'bull':
    # 牛市：放宽条件
    params['j_threshold'] = 20
    params['volume_ratio_threshold'] = 2.5
elif regime == 'bear':
    # 熊市：收紧条件或空仓
    params['j_threshold'] = 10
    params['position_pct'] = 0.05
```

---

### 3. 关于因子优化

**动态调整因子参数以最大化战损比/胜率**:

```python
from strategy_optimizer import StrategyOptimizer

optimizer = StrategyOptimizer(strategy_cls=DualLineBreathStrategy)

# 敏感性分析：找出最佳参数
sensitivity_df = optimizer.parameter_sensitivity_analysis(
    base_params={'j_threshold': 13, 'volume_ratio_threshold': 3.5},
    param_to_test='j_threshold',
    test_range=[5, 8, 10, 13, 15, 18, 20, 25],
    symbols=['000001', '000002', '600519'],
    objective='profit_factor'  # 盈亏比
)

# 找出盈亏比最高的参数
best_j = sensitivity_df.loc[sensitivity_df['avg_profit_factor'].idxmax(), 'j_threshold']
print(f"最优J阈值（盈亏比最大）: {best_j}")
```

---

## 🔍 数据验证

在运行策略前，验证数据完整性：

```python
import pandas as pd
from pathlib import Path

data_dir = Path('data')
csv_files = list(data_dir.glob('*.csv'))

print(f"总文件数: {len(csv_files)}")

# 检查单个文件
sample = pd.read_csv(data_dir / '000001.csv')
print(f"\n示例股票 (000001):")
print(f"  起始日期: {sample['date'].min()}")
print(f"  结束日期: {sample['date'].max()}")
print(f"  总行数: {len(sample)}")
print(f"  缺失值: {sample.isna().sum().sum()}")

# 如果起始日期不是2004年，说明下载有问题
if '2004' not in str(sample['date'].min()):
    print("\n⚠️ 警告: 数据未从2004年开始，请重新运行下载脚本!")
    print("   bash download_full_history.sh")
```

---

## 📊 预期结果

### 单票回测（示例）

**000001（平安银行）- 2020-2024**:
- 总收益率: 预期 +15% ~ +30%
- Sharpe比率: 预期 0.8 ~ 1.5
- 最大回撤: 预期 -15% ~ -25%
- 交易次数: 预期 10-20笔

**注意**: 实际结果取决于：
1. 数据周期（更长周期更准确）
2. 参数设置
3. 市场环境

### 参数优化后

预期改进：
- 交易次数: +50% ~ +100%
- Sharpe比率: +20% ~ +40%
- 胜率: +5% ~ +10%

---

## 🐛 常见错误

### 错误1: "Data file not found"
**解决**: 检查文件名格式，应该是`000001.csv`而非`000001.SZ.csv`

### 错误2: "time data does not match format"
**解决**: 已修复，日期格式改为`YYYY-MM-DD`

### 错误3: 交易记录为空
**解决**: 数据太短或参数太严，参考"交易次数少"解决方案

### 错误4: Tushare限流
**解决**: 
- 减少`--workers`数量（5→3）
- 等待10分钟后重试
- 升级Tushare账户权限

---

## 📞 获取帮助

1. 查看 `IMPLEMENTATION_STATUS.md` - 详细进度和待办
2. 查看 `README.md` - 完整文档
3. 检查日志文件 `download.log`
4. 查看回测结果 `backtest_results/`

---

**祝您回测顺利！🚀**


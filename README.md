# 量化交易平台 - 知行双线呼吸策略

**工业级A股量化交易系统**，集成规则策略、因子库、机器学习和组合回测。

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 🎯 项目特点

- ✅ **完整的A股特性支持**: T+1约束、印花税、涨跌停、停牌处理
- ✅ **严格时间序列验证**: 防止未来信息泄漏
- ✅ **模块化设计**: 回测引擎、指标库、因子库完全解耦
- ✅ **工业级代码**: 类型提示、完整文档、异常处理
- ✅ **GPU加速就绪**: LightGBM训练、因子并行计算
- ✅ **专业因子分析**: IC/ICIR、分位数、换手率（Alphalens风格）

---

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

### 3. 运行回测

#### 单票回测（规则策略）
```bash
python rule_strategy_backtest.py --symbol 000001
```

#### 多票测试
```bash
python test_dual_line_strategy.py
```

#### 参数优化
```bash
python strategy_optimizer.py
```

---

## 📚 项目架构

```
my_quant_project/
│
├── 📊 核心引擎
│   ├── backtest_engine.py         # 回测引擎（T+1、印花税、佣金）
│   ├── data_downloader.py         # 数据下载器
│   ├── data_quality.py            # 数据质量检查
│   └── strategy_optimizer.py      # 参数优化器（网格搜索、K-means）
│
├── 📈 策略库 (custom_strategies/)
│   ├── dual_line_breath.py        # 知行双线呼吸策略 ⭐核心
│   └── moving_average.py          # MA基准策略
│
├── 🔧 指标库 (custom_indicators/)
│   ├── zhixing_indicators.py      # 知行双线系统
│   ├── kdj.py                     # KDJ指标
│   ├── volume_breath.py           # 成交量呼吸度 ⭐创新
│   └── atr_stop.py                # ATR止损 + VWAP
│
├── 🧮 因子库 (factor_lib/)
│   ├── base.py                    # 因子引擎基类
│   ├── custom_factors.py          # 策略衍生因子（10个）
│   ├── preprocessing.py           # 预处理Pipeline
│   └── ic_analysis.py             # IC分析（Alphalens风格）
│
├── 🤖 ML模块 (待完成)
│   ├── feature_engineering.py     # 特征工程
│   ├── ml_trainer.py              # LightGBM训练
│   └── ml_strategy.py             # ML增强策略
│
├── 📋 配置与文档
│   ├── README.md                  # 本文档
│   ├── IMPLEMENTATION_STATUS.md   # 详细进度
│   ├── requirements.txt           # 依赖列表
│   └── stocklist.csv              # 股票池（5431只）
│
└── 📂 数据与结果
    ├── data/                      # 股票数据
    ├── backtest_results/          # 回测结果
    └── models/                    # ML模型
```

---

## 🎲 知行双线呼吸策略

### 策略逻辑

**买入条件（AND，4个条件同时满足）**:
1. ✅ **趋势确认**: 白线（双EMA） > 黄线（四均线）
2. ✅ **成交量活跃**: 呼吸度 > 3.5 （放量缩量交替）
3. ✅ **超卖信号**: J < 13 （KDJ超卖）
4. ✅ **价格区间**: 黄线 < 收盘价 < 白线 （回调到位）

**卖出条件（OR，任一触发）**:
1. ✅ **止损**: 收盘价跌破黄线 （趋势破坏）
2. ✅ **死叉**: 白线下穿黄线 （趋势反转）
3. ✅ **ATR止盈**: 回撤超过3倍ATR （保护利润）

**仓位管理**:
- 固定10%资金买入
- T+1约束：当日买入次日才能卖出
- 支持动态参数调整（根据市场环境）

### 参数优化

```python
from strategy_optimizer import StrategyOptimizer

optimizer = StrategyOptimizer(strategy_cls=DualLineBreathStrategy)

# 网格搜索
best_params, results = optimizer.grid_search(
    param_grid={
        'j_threshold': [5, 10, 13, 15, 20],
        'volume_ratio_threshold': [2.5, 3.0, 3.5, 4.0],
    },
    symbols=['000001', '000002', '600519'],
    objective='sharpe'
)
```

### 市场过滤器

```python
from strategy_optimizer import MarketRegimeDetector

detector = MarketRegimeDetector()
regime = detector.detect_regime(index_data)  # 'bull', 'bear', 'sideways'

# 根据市场环境动态调整参数
adjusted_params = detector.get_regime_adjusted_params(regime, base_params)
```

---

## 🧮 因子库

### 策略衍生因子（10个）

1. **TrendSpreadFactor**: 趋势价差
2. **PriceZoneFactor**: 价格相对位置
3. **KDJFactors**: K/D/J三值
4. **VolumeBreathRatioFactor**: 成交量呼吸度
5. **PriceVolumeCorrelationFactor**: 量价相关性
6. **VolumePullbackFactor**: 缩量回调
7. **VWAPRatioFactor**: VWAP比率
8. **ATRPositionFactor**: ATR止损空间
9. **RSVFactor**: 原始RSV值

### 因子计算示例

```python
from factor_lib.base import FactorEngine
from factor_lib.custom_factors import TrendSpreadFactor

# 创建引擎
engine = FactorEngine(data_dir='data', cache_dir='factor_cache')

# 加载数据
engine.load_data(symbols=['000001', '000002'], start_date='2020-01-01')

# 注册因子
engine.register_factor(TrendSpreadFactor(short_period=10))

# 计算
results = engine.compute_all()
```

### 因子预处理

```python
from factor_lib.preprocessing import FactorPreprocessor

preprocessor = FactorPreprocessor(
    method='mad',           # 极值处理：MAD法
    fill_method='median',   # 缺失值：中位数填充
    standardize=True,       # Z-score标准化
    neutralize=False,       # 行业中性化
)

clean_factors = preprocessor.fit_transform(factor_df, industry_map=industries)
```

### IC分析

```python
from factor_lib.ic_analysis import FactorAnalyzer

analyzer = FactorAnalyzer(output_dir='factor_analysis_results')

report = analyzer.generate_report(
    factor_name='my_factor',
    factor_panel=factor_df,
    price_panel=price_df,
    periods=[5, 10, 20]  # 预测周期
)

print(f"IC均值: {report['ic_stats'][5]['IC_mean']:.4f}")
print(f"IC_IR: {report['ic_stats'][5]['IC_IR']:.4f}")
```

---

## 📊 数据质量

### 质量检查

```python
from data_quality import DataQualityChecker

checker = DataQualityChecker(data_dir='data')

# 生成质量报告
report = checker.generate_quality_report('000001')
print(report)

# 清洗数据
clean_data = checker.process_stock(
    '000001',
    remove_suspension=True,      # 移除停牌日
    mark_limit_price=True,       # 标记涨跌停
    handle_outliers=True,        # 处理异常值
)
```

### 检查项

- ✅ 价格异常值（负数、极端涨跌幅）
- ✅ 成交量异常
- ✅ 停牌检测与过滤
- ✅ 涨跌停标记
- ✅ OHLC关系验证

---

## 🤖 机器学习（规划中）

### 特征工程

**55个因子**:
- 10个策略衍生因子
- 30个Alpha101精选因子
- 10个经典技术因子
- 5个行业因子

**标签生成（三重障碍法）**:
- 上轨：未来10日内+10%
- 下轨：未来10日内-5%
- 时间轨：10个交易日
- Label: 1（做多）, 0（不做）

### LightGBM训练

```python
from ml_trainer import MLTrainer

trainer = MLTrainer(
    feature_path='features.pkl',
    label_path='labels.pkl',
    model_type='lightgbm',
    use_gpu=True
)

# 训练
model = trainer.train(
    train_start='2019-01-01',
    train_end='2022-12-31',
    valid_start='2023-01-01',
    valid_end='2023-06-30'
)

# SHAP分析
trainer.analyze_feature_importance(model)
```

### ML增强策略

```python
# 模型预测 + 规则筛选
每日收盘:
  1. 计算所有股票的55个因子
  2. 模型预测买入概率
  3. 选择概率Top 10的股票
  4. 对Top 10应用规则筛选（趋势+呼吸度+J值）
  5. 通过规则的股票买入（10%仓位）
  6. 使用规则的止损/止盈逻辑
```

---

## 📈 回测结果

### 结果输出

**JSON指标** (`backtest_results/xxx_metrics.json`):
```json
{
  "sharpe_ratio": 1.23,
  "max_drawdown_pct": -15.6,
  "total_return_pct": 45.2,
  "total_trades": 23,
  "win_rate": 0.65,
  "profit_factor": 2.1
}
```

**交易详情** (新增):
- 每笔买入/卖出的时间
- 交易价格
- 持仓周期
- 盈亏（金额和百分比）

**可视化**:
- 累计收益曲线（策略 vs 指数）
- 交易标记（买入/卖出点）
- 指标时间序列
- IC时序图、分位数收益图

---

## 🔧 高级功能

### 1. 动态参数调整（K-means）

```python
from strategy_optimizer import StrategyOptimizer

optimizer = StrategyOptimizer(strategy_cls=DualLineBreathStrategy)

# 使用K-means动态计算J阈值
j_threshold = optimizer.compute_dynamic_j_threshold(
    j_values=kdj_j_series,
    method='kmeans',
    n_clusters=3
)
```

### 2. 组合回测

```python
from portfolio_backtest import PortfolioBacktest

portfolio = PortfolioBacktest(
    strategy_cls=DualLineBreathStrategy,
    stock_pool=['000001', '000002', '600519', ...],
    max_positions=10,      # 最大持仓数
    position_pct=0.10,     # 单只仓位
)

result = portfolio.run(start_date='2020-01-01', end_date='2024-12-31')
```

### 3. 参数敏感性分析

```python
sensitivity_df = optimizer.parameter_sensitivity_analysis(
    base_params={'j_threshold': 13},
    param_to_test='j_threshold',
    test_range=[5, 8, 10, 13, 15, 18, 20],
    symbols=['000001', '000002'],
    objective='sharpe'
)
```

---

## 📖 使用建议

### 数据周期

- ⚠️ **最少3年数据**：策略验证需要经历不同市场环境
- ✅ **推荐**: 2004-2025完整牛熊周期
- 📊 **分段分析**: 
  - 牛市：2006-2007, 2014-2015, 2020-2021
  - 熊市：2008, 2018
  - 震荡：其他年份

### 参数优化

1. **初始测试**: 使用默认参数（J<13, 呼吸度>3.5）
2. **网格搜索**: 优化J阈值和呼吸度阈值
3. **Walk-forward**: 滚动优化，避免过拟合
4. **市场过滤**: 根据大盘环境动态调整

### 因子选择

1. **IC筛选**: 只保留IC_IR > 0.5的因子
2. **相关性检查**: 剔除高度相关的冗余因子（相关系数>0.8）
3. **稳定性验证**: 因子在不同时期IC符号一致
4. **换手率控制**: 避免高换手率因子（增加交易成本）

### 风险控制

- 单只股票最大仓位：10%
- 最大持仓数：10只
- 止损：-5% 硬止损 或 跌破黄线
- 止盈：ATR 3倍移动止盈
- 现金缓冲：10%（应对滑点和费用）

---

## 🏆 性能优化

### GPU加速

```python
# LightGBM GPU训练
params = {
    'device': 'gpu',
    'gpu_platform_id': 0,
    'gpu_device_id': 0,
}

# 因子并行计算
engine = FactorEngine(data_dir='data', n_jobs=-1)  # 使用所有CPU核心
```

### 缓存策略

```python
# 因子缓存（避免重复计算）
engine = FactorEngine(data_dir='data', cache_dir='factor_cache')
results = engine.compute_all(use_cache=True)

# 清空缓存（更新数据后）
engine.clear_cache()
```

---

## 🐛 常见问题

### Q1: 交易次数太少怎么办？

**原因**: 4个买入条件同时满足的概率较低

**解决方案**:
1. 放宽J阈值（13→15或20）
2. 降低呼吸度阈值（3.5→3.0或2.5）
3. 使用动态阈值（K-means）
4. 应用于整个股票池（每日筛选多只股票）

### Q2: 为什么使用收盘价？

**原因**:
- 收盘价噪声更少（全天交易后的共识价格）
- 流动性更好（收盘集合竞价）
- 研究可复现性更好（业界标准）
- 实盘可行（收盘计算信号，次日开盘执行）

### Q3: 如何防止过拟合？

**方法**:
1. 严格时间序列分割（不随机shuffle）
2. Walk-forward分析
3. 验证集Sharpe > 训练集Sharpe × 0.7
4. 参数简单化（少于5个可调参数）
5. 样本外测试（至少保留20%数据）

### Q4: 数据下载失败？

**检查**:
1. Tushare Token是否正确
2. 是否添加`--overwrite`标志
3. 网络连接是否正常
4. 是否触发Tushare限流（降低workers数）

---

## 📚 参考文档

- [Backtrader官方文档](https://www.backtrader.com/docu/)
- [Tushare Pro文档](https://tushare.pro/document/2)
- [LightGBM文档](https://lightgbm.readthedocs.io/)
- [Alphalens文档](https://quantopian.github.io/alphalens/)

---

## 📝 待完成功能

- [ ] Alpha101因子集成（精选30个）
- [ ] 技术因子库（动量、波动率、RSI、MACD）
- [ ] 行业因子（行业轮动、排名、中性化）
- [ ] 特征工程模块（55个因子批量计算）
- [ ] LightGBM训练（GPU加速、SHAP分析）
- [ ] ML增强策略
- [ ] 组合回测引擎

详见 `IMPLEMENTATION_STATUS.md`

---

## 🤝 贡献

欢迎提交Issue和Pull Request！

---

## 📄 License

MIT License

---

**作者**: 量化分析团队  
**更新**: 2025-11-04  
**版本**: 1.0 Beta

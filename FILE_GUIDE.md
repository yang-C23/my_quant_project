
# 文件使用指南

本文档详细说明每个文件的作用、使用方法和使用流程。

---

## 📁 项目结构总览

```
my_quant_project/
├── 📊 数据模块
│   ├── data_downloader.py           # 数据下载器
│   ├── download_full_history.sh      # 批量下载脚本
│   ├── download_indices.sh           # 指数数据下载
│   └── data_quality.py               # 数据质量检查
│
├── 🔧 回测引擎
│   └── backtest_engine.py            # 核心回测引擎
│
├── 📈 技术指标
│   └── custom_indicators/            # 自定义指标库
│       ├── zhixing_indicators.py     # 知行双线
│       ├── kdj.py                    # KDJ指标
│       ├── volume_breath.py          # 成交量呼吸度
│       └── atr_stop.py               # ATR止损
│
├── 🎯 交易策略
│   └── custom_strategies/            # 策略库
│       ├── dual_line_breath.py       # 规则策略
│       └── ml_strategy.py            # ML策略
│
├── 🔬 因子库
│   └── factor_lib/                   # 因子计算模块
│       ├── base.py                   # 因子基类
│       ├── custom_factors.py         # 自定义因子（10个）
│       ├── alpha101_factors.py       # Alpha101因子（30个）
│       ├── technical_factors.py      # 技术因子（10个）
│       ├── industry_factors.py       # 行业因子（5个）
│       ├── preprocessing.py          # 因子预处理
│       ├── ic_analysis.py            # IC分析
│       └── alpha_integration.py      # Alpha因子整合
│
├── 🤖 机器学习
│   ├── feature_engineering.py        # 特征工程
│   ├── ml_trainer.py                 # ML训练器
│   └── stop_loss_strategies.py       # 止损策略库
│
├── 🧪 测试与优化
│   ├── test_dual_line_strategy.py    # 单票测试
│   ├── condition_ablation_test.py    # 条件消融实验
│   ├── strategy_optimizer.py         # 参数优化
│   └── run_full_market_backtest.py   # 全市场回测
│
├── 📊 组合回测
│   ├── portfolio_backtest.py         # 组合回测模块
│   └── rule_strategy_backtest.py     # 规则策略回测脚本
│
├── 📚 文档
│   ├── README.md                     # 项目说明
│   ├── QUICK_START.md                # 快速开始
│   ├── USAGE_GUIDE.md                # 使用指南
│   ├── PROJECT_SUMMARY.md            # 项目总结
│   ├── FILE_GUIDE.md                 # 本文档
│   └── IMPLEMENTATION_STATUS.md      # 实现状态
│
└── 🛠️ 辅助工具
    ├── quick_test.sh                 # 快速测试脚本
    └── install_ml_dependencies.sh    # ML依赖安装
```

---

## 🚀 完整使用流程

### 阶段1: 环境准备（首次运行必须）

```bash
# 1. 激活虚拟环境
source /home/yang/venvs/my_quant_env/bin/activate

# 2. 安装ML依赖（如果还没安装）
bash install_ml_dependencies.sh

# 3. 下载数据
bash download_full_history.sh        # 股票数据
bash download_indices.sh              # 指数数据

# 4. 快速测试
bash quick_test.sh
```

### 阶段2: 规则策略开发与测试

```bash
# 1. 单票测试（3只代表性股票）
python test_dual_line_strategy.py

# 2. 条件消融实验（找出最优条件组合）
python condition_ablation_test.py

# 3. 参数优化（找出最优参数）
python strategy_optimizer.py

# 4. 单票详细回测
python rule_strategy_backtest.py --symbol 000001 --j-threshold 15 --volume-ratio 2.5

# 5. 全市场回测
python run_full_market_backtest.py --stocklist stocklist.csv
```

### 阶段3: 因子分析

```bash
# 1. 计算单只股票的因子
python feature_engineering.py 000001

# 2. 因子有效性分析（IC分析）
python -c "
from factor_lib.ic_analysis import ICAnalyzer
import pandas as pd

# 加载特征
X = pd.read_csv('ml_data_test/features.csv')
y = pd.read_csv('ml_data_test/labels.csv', header=None)[0]

# IC分析
analyzer = ICAnalyzer()
ic_df = analyzer.calculate_ic(X, y)
print(ic_df.head(20))
"

# 3. 整合开源Alpha因子
python factor_lib/alpha_integration.py data/000001.csv
```

### 阶段4: 机器学习模型训练

```bash
# 1. 构建训练数据集
python -c "
from feature_engineering import FeatureEngineer

engineer = FeatureEngineer()
X, y = engineer.build_multi_stock_dataset(
    stock_list=['000001', '000002', '002594', '600519', '000651'],
    save_path='ml_data_train'
)
"

# 2. 训练模型
python -c "
from ml_trainer import LightGBMTrainer, time_series_cv_train
import pandas as pd

X = pd.read_csv('ml_data_train/features.csv')
y = pd.read_csv('ml_data_train/labels.csv', header=None)[0]

trainer, cv_results = time_series_cv_train(
    X, y,
    n_splits=5,
    trainer_params={'use_gpu': True},
    save_dir='models/lgbm_cv'
)

trainer.save_model('models/lgbm_final.txt')
"

# 3. 特征重要性和SHAP分析
python -c "
from ml_trainer import LightGBMTrainer
import pandas as pd

trainer = LightGBMTrainer(use_gpu=True)
trainer.load_model('models/lgbm_final.txt')

X = pd.read_csv('ml_data_train/features.csv')
trainer.plot_feature_importance(top_n=20, save_path='models/feature_importance.png')
trainer.shap_analysis(X.sample(500), save_dir='models/shap')
"
```

### 阶段5: ML策略回测

```bash
# ML策略组合回测
python portfolio_backtest.py --strategy ml --model-path models/lgbm_final.txt
```

---

## 📄 详细文件说明

### 1. 数据模块

#### `data_downloader.py`
**作用**: Tushare数据下载器

**主要功能**:
- 从Tushare Pro下载A股日线数据
- 支持前复权/后复权/不复权
- 多线程并行下载
- 增量更新或覆盖模式

**使用方法**:
```bash
python data_downloader.py \
    --stocklist stocklist.csv \
    --start 20040101 \
    --end today \
    --adjust qfq \
    --workers 5 \
    --out data
```

**参数说明**:
- `--stocklist`: 股票列表CSV文件（必须包含`ts_code`列）
- `--start`: 开始日期（YYYYMMDD格式）
- `--end`: 结束日期（YYYYMMDD或`today`）
- `--adjust`: 复权类型（`qfq`前复权, `hfq`后复权, `none`不复权）
- `--workers`: 并行下载线程数
- `--overwrite`: 覆盖已存在的文件
- `--out`: 输出目录

#### `download_full_history.sh`
**作用**: 一键下载所有股票的完整历史数据

**使用方法**:
```bash
bash download_full_history.sh
```

**配置**: 编辑脚本修改日期范围、复权类型等参数

#### `download_indices.sh`
**作用**: 下载指数数据（沪深300、中证1000等）

**使用方法**:
```bash
bash download_indices.sh
```

#### `data_quality.py`
**作用**: 数据质量检查工具

**功能**:
- 检测缺失值
- 统计停牌天数
- 统计涨跌停天数
- 识别异常数据

**使用方法**:
```bash
# 检查单个文件
python data_quality.py data/000001.csv

# 批量检查
python data_quality.py
```

---

### 2. 回测引擎

#### `backtest_engine.py`
**作用**: 核心回测引擎，基于Backtrader

**主要组件**:
- `TushareDailyCSV`: 数据加载器
- `AShareCommissionScheme`: A股佣金+印花税模型
- `BacktestResult`: 回测结果数据类
- `run_backtest()`: 统一回测接口

**使用方法**:
```python
from backtest_engine import run_backtest
from custom_strategies.dual_line_breath import DualLineBreathStrategy

result = run_backtest(
    symbol='000001',
    strategy_class=DualLineBreathStrategy,
    strategy_params={'j_threshold': 15, 'volume_ratio_threshold': 2.5},
    initial_cash=100000.0
)
```

**特性**:
- ✅ A股T+1交易限制
- ✅ 佣金（万三）+ 印花税（千一）
- ✅ 最小佣金5元
- ✅ 滑点模拟
- ✅ 多股票支持

---

### 3. 技术指标模块

#### `custom_indicators/zhixing_indicators.py`
**作用**: 知行双线指标

**指标**:
- `ZhiXingShortTrend`: 知行短期趋势线（白线）= EMA(EMA(Close, 10), 10)
- `ZhiXingMultiAverage`: 知行多空线（黄线）= (MA14 + MA28 + MA57 + MA114) / 4
- `ZhiXingTrendSpread`: 趋势强度 = (白线 - 黄线) / 黄线
- `PriceZoneIndicator`: 价格位置 = (Close - 黄线) / (白线 - 黄线)

**使用方法**:
```python
from custom_indicators import ZhiXingShortTrend, ZhiXingMultiAverage

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.white_line = ZhiXingShortTrend(self.data)
        self.yellow_line = ZhiXingMultiAverage(self.data)
    
    def next(self):
        if self.white_line[0] > self.yellow_line[0]:
            print("趋势向上")
```

#### `custom_indicators/kdj.py`
**作用**: KDJ指标

**指标**:
- `KDJ`: 标准KDJ指标（K、D、J值）
- `JOversoldSignal`: J值超卖信号（J < threshold）
- `KDJCross`: KDJ金叉死叉信号

#### `custom_indicators/volume_breath.py`
**作用**: 成交量分析指标

**指标**:
- `VolumeBreath`: 成交量呼吸度 = AVGHIGH / AVGLOW
- `PriceVolumeCorrelation`: 量价相关性
- `VolumePullback`: 缩量回调检测

#### `custom_indicators/atr_stop.py`
**作用**: ATR止损和VWAP指标

**指标**:
- `ATRTrailingStop`: ATR追踪止损
- `ATRStopSignal`: ATR止损信号
- `VWAP`: 成交量加权平均价
- `VWAPRatio`: 价格/VWAP比率

---

### 4. 交易策略

#### `custom_strategies/dual_line_breath.py`
**作用**: 知行双线呼吸策略（规则策略）

**买入条件**（4个，全部满足）:
1. `COND_TREND`: 白线 > 黄线（趋势向上）
2. `COND_ACTIVITY`: 成交量呼吸度 > 阈值（量价活跃）
3. `COND_ENTRY_J`: J < 阈值（超卖）
4. `COND_PRICE_ZONE`: 价格在白黄线之间

**卖出条件**（任一触发）:
1. 收盘价跌破黄线
2. 白线死叉黄线
3. ATR追踪止损触发

**参数**:
- `white_period`: 白线周期（默认10）
- `j_threshold`: J值阈值（默认15）
- `volume_ratio_threshold`: 成交量呼吸度阈值（默认2.5）
- `position_size`: 仓位比例（默认0.10）

**使用方法**:
```python
from custom_strategies.dual_line_breath import DualLineBreathStrategy

# 在回测中使用
cerebro.addstrategy(
    DualLineBreathStrategy,
    j_threshold=15.0,
    volume_ratio_threshold=2.5
)
```

#### `custom_strategies/ml_strategy.py`
**作用**: 机器学习选股策略

**策略逻辑**:
1. 使用训练好的ML模型预测信号强度
2. 选择Top N只预测最好的股票
3. 结合规则筛选（趋势、成交量）
4. 固定仓位管理（每只10%）
5. 每周/每月调仓

**参数**:
- `model_path`: 模型文件路径
- `top_n`: 选择Top N只股票（默认10）
- `position_size`: 每只股票仓位（默认0.10）
- `rebalance_freq`: 调仓频率（`daily`/`weekly`/`monthly`）
- `use_rule_filter`: 是否使用规则筛选

**使用方法**:
```python
from custom_strategies.ml_strategy import MLSignalStrategy

cerebro.addstrategy(
    MLSignalStrategy,
    model_path='models/lgbm_final.txt',
    top_n=10,
    rebalance_freq='weekly'
)
```

---

### 5. 因子库

#### `factor_lib/custom_factors.py`
**作用**: 自定义因子（10个）

**因子列表**:
1. `TrendSpreadFactor`: 趋势强度
2. `PriceZoneFactor`: 价格位置
3. `KDJ_JFactor`: KDJ的J值
4. `KDJ_SpreadFactor`: K-D价差
5. `VolumeBreathRatioFactor`: 成交量呼吸度
6. `PriceVolumeCorrelationFactor`: 量价相关性
7. `VolumePullbackFactor`: 缩量回调
8. `VWAPRatioFactor`: VWAP比率
9. `ATRPositionFactor`: ATR位置
10. `RSVFactor`: RSV值

**使用方法**:
```python
from factor_lib.custom_factors import TrendSpreadFactor

factor = TrendSpreadFactor()
trend_strength = factor.calculate(data)
```

#### `factor_lib/alpha101_factors.py`
**作用**: WorldQuant Alpha101因子（30个精选）

**分类**:
- 动量/反转类（10个）
- 量价关系类（10个）
- 波动率/风险类（5个）
- 技术形态类（5个）

**使用方法**:
```python
from factor_lib.alpha101_factors import Alpha101Factors

alpha = Alpha101Factors(data)
all_factors = alpha.calculate_all()  # 计算所有30个
selected = alpha.calculate_selected([1, 2, 3])  # 计算指定的
```

#### `factor_lib/technical_factors.py`
**作用**: 经典技术因子（10个）

**因子列表**:
- ROC（变化率）
- Momentum（动量）
- Price Acceleration（价格加速度）
- ATR（平均真实波幅）
- Bollinger Bands Width（布林带宽度）
- MACD（MACD线、信号线、柱状图）
- ADX（平均趋向指标）
- Aroon（阿隆指标）
- RSI（相对强弱指标）
- Stochastic（随机指标）

**使用方法**:
```python
from factor_lib.technical_factors import TechnicalFactors

tech = TechnicalFactors(data)
factors = tech.calculate_all()
```

#### `factor_lib/industry_factors.py`
**作用**: 行业因子（5个）

**因子列表**:
1. `industry_momentum`: 行业动量
2. `rank_in_industry`: 行业内排名
3. `industry_neutral_momentum`: 行业中性化动量
4. `industry_volatility`: 行业波动率
5. `corr_with_industry`: 与行业相关性

**使用方法**:
```python
from factor_lib.industry_factors import IndustryFactors

industry = IndustryFactors(data, industry_mapping, stock_code)
factors = industry.calculate_all()
```

#### `factor_lib/preprocessing.py`
**作用**: 因子预处理Pipeline

**功能**:
- 极值处理（Winsorization）
- 缺失值填充
- 标准化（Z-score/Min-Max/Robust）
- 行业中性化

**使用方法**:
```python
from factor_lib.preprocessing import FactorPreprocessor

preprocessor = FactorPreprocessor(
    winsorize_method='quantile',
    fill_method='forward',
    standardize_method='zscore'
)

X_processed = preprocessor.fit_transform(X)
```

#### `factor_lib/ic_analysis.py`
**作用**: 因子有效性分析（IC分析）

**功能**:
- IC计算（信息系数）
- IR计算（信息比率）
- 多周期IC分析
- IC时间序列分析
- 分位数收益分析
- 换手率分析

**使用方法**:
```python
from factor_lib.ic_analysis import ICAnalyzer

analyzer = ICAnalyzer()
ic_df = analyzer.calculate_ic(X, y, forward_periods=[5, 10, 20])
analyzer.plot_ic_series(ic_df, 'ic_analysis.png')
```

#### `factor_lib/alpha_integration.py`
**作用**: 整合开源Alpha101/191因子库

**功能**:
- 调用开源alpha101/191实现
- 与本项目实现对比验证
- 统一因子接口

**使用方法**:
```python
from factor_lib.alpha_integration import calculate_integrated_alphas

factors = calculate_integrated_alphas(
    csv_file='data/000001.csv',
    use_open_source=True,
    alpha101_list=[1, 2, 3, 4, 6, 7, 8, 9, 10]
)
```

---

### 6. 机器学习模块

#### `feature_engineering.py`
**作用**: 特征工程管理器

**功能**:
- 批量计算所有55个因子
- 三重障碍法标签生成
- 因子预处理
- 数据集构建

**使用方法**:
```python
from feature_engineering import FeatureEngineer

engineer = FeatureEngineer()

# 单只股票
X, y = engineer.build_dataset(
    stock_code='000001',
    label_type='triple_barrier'
)

# 多只股票
X, y = engineer.build_multi_stock_dataset(
    stock_list=['000001', '000002', '002594'],
    save_path='ml_data'
)
```

**标签类型**:
- `triple_barrier`: 三重障碍法（推荐）
- `continuous`: 连续标签（未来收益率）

#### `ml_trainer.py`
**作用**: LightGBM训练器

**功能**:
- LightGBM模型训练（分类/回归）
- GPU加速支持
- 时间序列交叉验证
- Early Stopping
- 特征重要性分析
- SHAP分析
- 模型保存/加载

**使用方法**:
```python
from ml_trainer import LightGBMTrainer, time_series_cv_train

# 时间序列CV训练
trainer, cv_results = time_series_cv_train(
    X, y,
    n_splits=5,
    trainer_params={'use_gpu': True},
    save_dir='models/lgbm_cv'
)

# 保存模型
trainer.save_model('models/lgbm_final.txt')

# 特征重要性
trainer.plot_feature_importance(top_n=20)

# SHAP分析
trainer.shap_analysis(X.sample(500))
```

#### `stop_loss_strategies.py`
**作用**: 增强止损策略库

**策略类型**:
1. `FixedPercentStopLoss`: 固定比例止损
2. `TrailingStopLoss`: 移动止损
3. `ATRStopLoss`: ATR止损
4. `BollingerBandStopLoss`: 布林带止损
5. `MAStopLoss`: 移动平均止损
6. `TimeBasedStopLoss`: 时间止损
7. `ProfitTargetStopLoss`: 盈亏比止损
8. `DrawdownStopLoss`: 回撤止损
9. `CombinedStopLoss`: 组合止损

**预定义方案**:
- `conservative`: 保守型（固定5%）
- `moderate`: 稳健型（固定8% + 时间15天）
- `aggressive`: 激进型（追踪12%）
- `atr`: ATR止损（2倍ATR）
- `combined`: 组合止损（推荐）

**使用方法**:
```python
from stop_loss_strategies import get_stop_loss_strategy

# 在策略中使用
stop_loss = get_stop_loss_strategy(
    'combined',
    self.data,
    entry_price=self.data.close[0]
)

# 检查止损
should_stop, reason = stop_loss.should_stop(self.data.close[0])
if should_stop:
    self.sell()
```

---

### 7. 测试与优化

#### `test_dual_line_strategy.py`
**作用**: 单票快速测试脚本

**测试股票**:
- 000001（平安银行）- 低波动
- 000002（万科A）- 中等波动
- 002594（比亚迪）- 高波动

**使用方法**:
```bash
python test_dual_line_strategy.py
```

#### `condition_ablation_test.py`
**作用**: 买入条件消融实验

**功能**:
- 测试4个买入条件的单独效果
- 测试所有条件组合（15种）
- 找出最优条件组合

**使用方法**:
```bash
python condition_ablation_test.py
```

**输出**:
- `backtest_results/condition_ablation/condition_combinations.csv`: 所有组合结果
- `backtest_results/condition_ablation/summary.txt`: 结果摘要

#### `strategy_optimizer.py`
**作用**: 参数优化工具

**优化参数**:
- `j_threshold`: J值阈值
- `volume_ratio_threshold`: 成交量呼吸度阈值

**使用方法**:
```bash
python strategy_optimizer.py
```

**网格搜索空间**:
- `j_threshold`: [5, 10, 13, 15, 20]
- `volume_ratio`: [2.0, 2.5, 3.0, 3.5, 4.0]

#### `run_full_market_backtest.py`
**作用**: 全市场回测脚本

**功能**:
- 全市场组合回测
- 按行业分组回测（可选）
- 使用最优参数

**使用方法**:
```bash
# 基本用法
python run_full_market_backtest.py --stocklist stocklist.csv

# 自定义参数
python run_full_market_backtest.py \
    --stocklist stocklist.csv \
    --start-date 2020-01-01 \
    --end-date 2024-12-31 \
    --initial-cash 1000000 \
    --max-positions 10 \
    --j-threshold 15.0 \
    --volume-ratio 2.5 \
    --stop-loss-type combined
```

---

### 8. 组合回测

#### `portfolio_backtest.py`
**作用**: 组合回测框架

**功能**:
- 多股票数据加载
- 资金池管理
- 最大持仓限制
- 组合级性能分析
- 与基准指数对比

**使用方法**:
```python
from portfolio_backtest import run_portfolio_backtest
from custom_strategies.dual_line_breath import DualLineBreathStrategy

result = run_portfolio_backtest(
    stock_list_file="stocklist.csv",
    strategy_class=DualLineBreathStrategy,
    strategy_params={'j_threshold': 15, 'volume_ratio_threshold': 2.5},
    initial_cash=1000000.0,
    max_positions=10
)
```

#### `rule_strategy_backtest.py`
**作用**: 规则策略回测脚本

**使用方法**:
```bash
python rule_strategy_backtest.py \
    --symbol 000001 \
    --start-date 2020-01-01 \
    --end-date 2024-12-31 \
    --j-threshold 15 \
    --volume-ratio 2.5
```

---

### 9. 辅助工具

#### `quick_test.sh`
**作用**: 快速测试脚本

**功能**:
- 检查数据文件
- 运行单票测试
- 数据质量检查
- 环境检查

**使用方法**:
```bash
bash quick_test.sh
```

#### `install_ml_dependencies.sh`
**作用**: 安装ML相关依赖

**安装内容**:
- LightGBM
- SHAP
- scikit-optimize

**使用方法**:
```bash
bash install_ml_dependencies.sh
```

---

## 🎯 常见使用场景

### 场景1: 新手快速上手

```bash
# 1. 环境准备
bash quick_test.sh

# 2. 单票测试
python test_dual_line_strategy.py

# 3. 查看结果
cat backtest_results/002594_dual_line_metrics.json
```

### 场景2: 策略参数优化

```bash
# 1. 条件消融实验
python condition_ablation_test.py

# 2. 参数网格搜索
python strategy_optimizer.py

# 3. 使用最优参数回测
python rule_strategy_backtest.py --symbol 000001 --j-threshold 15 --volume-ratio 2.5
```

### 场景3: 因子开发与分析

```bash
# 1. 计算因子
python feature_engineering.py 000001

# 2. IC分析
python -c "from factor_lib.ic_analysis import ICAnalyzer; ..."

# 3. 因子预处理
python -c "from factor_lib.preprocessing import FactorPreprocessor; ..."
```

### 场景4: ML模型训练与回测

```bash
# 1. 构建数据集
python -c "from feature_engineering import FeatureEngineer; ..."

# 2. 训练模型
python -c "from ml_trainer import time_series_cv_train; ..."

# 3. ML策略回测
python portfolio_backtest.py --strategy ml --model-path models/lgbm_final.txt
```

### 场景5: 全市场回测

```bash
# 使用最优参数进行全市场回测
python run_full_market_backtest.py \
    --stocklist stocklist.csv \
    --j-threshold 15.0 \
    --volume-ratio 2.5 \
    --max-positions 10
```

---

## ❓ 常见问题

### Q1: 找不到数据文件？
**A**: 运行 `bash download_full_history.sh` 下载数据

### Q2: LightGBM未安装？
**A**: 运行 `bash install_ml_dependencies.sh`

### Q3: 回测交易次数为0？
**A**: 
1. 条件过于严格，尝试放宽参数
2. 运行全市场回测，而非单票
3. 检查数据质量

### Q4: 如何选择止损策略？
**A**: 查看 `stop_loss_strategies.py`，推荐使用 `combined`

### Q5: 如何添加自定义因子？
**A**: 在 `factor_lib/custom_factors.py` 中继承 `FactorBase` 类

---

## 📞 获取帮助

1. **查看文档**: `README.md`, `USAGE_GUIDE.md`
2. **查看代码注释**: 每个模块都有详细的docstring
3. **运行示例**: 每个模块的 `if __name__ == "__main__"` 部分

---

**祝使用愉快！🚀**


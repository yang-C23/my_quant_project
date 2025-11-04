"""
WorldQuant Alpha101 精选因子实现
===================================
精选30个最相关的动量、量价、反转类因子

参考: https://arxiv.org/abs/1601.00991
"""

import numpy as np
import pandas as pd
from typing import Optional
import warnings
warnings.filterwarnings('ignore')


class Alpha101Operators:
    """Alpha101算子库"""
    
    @staticmethod
    def ts_sum(df: pd.DataFrame, window: int) -> pd.DataFrame:
        """时间序列求和"""
        return df.rolling(window=window, min_periods=window//2).sum()
    
    @staticmethod
    def ts_mean(df: pd.DataFrame, window: int) -> pd.DataFrame:
        """时间序列均值"""
        return df.rolling(window=window, min_periods=window//2).mean()
    
    @staticmethod
    def ts_std(df: pd.DataFrame, window: int) -> pd.DataFrame:
        """时间序列标准差"""
        return df.rolling(window=window, min_periods=window//2).std()
    
    @staticmethod
    def ts_max(df: pd.DataFrame, window: int) -> pd.DataFrame:
        """时间序列最大值"""
        return df.rolling(window=window, min_periods=window//2).max()
    
    @staticmethod
    def ts_min(df: pd.DataFrame, window: int) -> pd.DataFrame:
        """时间序列最小值"""
        return df.rolling(window=window, min_periods=window//2).min()
    
    @staticmethod
    def ts_rank(df: pd.DataFrame, window: int) -> pd.DataFrame:
        """时间序列排名（最近N天中当前值的排名）"""
        return df.rolling(window=window, min_periods=window//2).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1]
        )
    
    @staticmethod
    def ts_argmax(df: pd.DataFrame, window: int) -> pd.DataFrame:
        """时间序列最大值的位置（从最近往前数）"""
        return df.rolling(window=window, min_periods=window//2).apply(
            lambda x: window - x.argmax() - 1
        )
    
    @staticmethod
    def ts_argmin(df: pd.DataFrame, window: int) -> pd.DataFrame:
        """时间序列最小值的位置（从最近往前数）"""
        return df.rolling(window=window, min_periods=window//2).apply(
            lambda x: window - x.argmin() - 1
        )
    
    @staticmethod
    def ts_corr(x: pd.DataFrame, y: pd.DataFrame, window: int) -> pd.DataFrame:
        """时间序列相关性"""
        return x.rolling(window=window, min_periods=window//2).corr(y)
    
    @staticmethod
    def ts_cov(x: pd.DataFrame, y: pd.DataFrame, window: int) -> pd.DataFrame:
        """时间序列协方差"""
        return x.rolling(window=window, min_periods=window//2).cov(y)
    
    @staticmethod
    def ts_delta(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """N天变化"""
        return df.diff(period)
    
    @staticmethod
    def ts_returns(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """N天收益率"""
        return df.pct_change(period)
    
    @staticmethod
    def rank(df: pd.DataFrame) -> pd.DataFrame:
        """横截面排名（0-1标准化）"""
        return df.rank(axis=1, pct=True)
    
    @staticmethod
    def scale(df: pd.DataFrame, k: float = 1.0) -> pd.DataFrame:
        """缩放（使绝对值之和为k）"""
        return df.div(df.abs().sum(axis=1), axis=0) * k
    
    @staticmethod
    def sign(df: pd.DataFrame) -> pd.DataFrame:
        """符号函数"""
        return np.sign(df)
    
    @staticmethod
    def decay_linear(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """线性衰减加权移动平均
        
        最近的权重最高：period, period-1, ..., 2, 1
        例如：period=5时，权重=[5,4,3,2,1]，归一化后=[5/15, 4/15, 3/15, 2/15, 1/15]
        """
        weights = np.arange(1, period + 1)
        weights = weights / weights.sum()
        
        def weighted_avg(x):
            if len(x) < period:
                return np.nan
            return (x * weights).sum()
        
        return df.rolling(window=period, min_periods=period).apply(weighted_avg)


class Alpha101Factors:
    """
    Alpha101 精选因子（30个核心因子）
    
    分类：
    - 动量/反转类（10个）
    - 量价关系类（10个）
    - 波动率/风险类（5个）
    - 技术形态类（5个）
    """
    
    def __init__(self, data: pd.DataFrame):
        """
        初始化Alpha101因子计算器
        
        Parameters
        ----------
        data : pd.DataFrame
            包含列：['date', 'open', 'high', 'low', 'close', 'volume']
            如果是多股票，需要有'ts_code'列
        """
        self.data = data.copy()
        self.ops = Alpha101Operators()
        
        # 确保数据按日期排序
        if 'date' in self.data.columns:
            self.data = self.data.sort_values('date')
        
        # 提取基础列
        self.open = self.data['open']
        self.high = self.data['high']
        self.low = self.data['low']
        self.close = self.data['close']
        self.volume = self.data['volume']
        
        # 预计算常用指标
        self.returns = self.ops.ts_returns(self.close, 1)
        self.vwap = (self.high + self.low + self.close) / 3  # 简化VWAP
    
    # ============================================================
    # 动量/反转类因子（10个）
    # ============================================================
    
    def alpha001(self) -> pd.Series:
        """
        Alpha#1: 动量反转因子
        
        (rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5)
        
        思想：当收益为负时，考虑波动率；否则直接看价格，找5天内最大值位置
        """
        inner = self.close.copy()
        condition = self.returns < 0
        inner[condition] = self.ops.ts_std(self.returns, 20)[condition]
        
        power = inner ** 2
        argmax = self.ops.ts_argmax(power, 5)
        return self.ops.rank(argmax) - 0.5
    
    def alpha002(self) -> pd.Series:
        """
        Alpha#2: 价格-成交量相关性反转
        
        (-1 * correlation(rank(delta(log(volume), 2)), rank(((close - open) / open)), 6))
        
        思想：成交量变化与涨跌幅的负相关性
        """
        log_vol_delta = self.ops.ts_delta(np.log(self.volume + 1), 2)
        price_change = (self.close - self.open) / (self.open + 1e-8)
        
        corr = self.ops.ts_corr(
            self.ops.rank(log_vol_delta),
            self.ops.rank(price_change),
            6
        )
        return -1 * corr
    
    def alpha003(self) -> pd.Series:
        """
        Alpha#3: 开盘-收盘相关性
        
        (-1 * correlation(rank(open), rank(volume), 10))
        
        思想：开盘价与成交量的负相关
        """
        return -1 * self.ops.ts_corr(
            self.ops.rank(self.open),
            self.ops.rank(self.volume),
            10
        )
    
    def alpha004(self) -> pd.Series:
        """
        Alpha#4: 低价排名因子
        
        (-1 * Ts_Rank(rank(low), 9))
        
        思想：最低价在9天内的时间序列排名（反转）
        """
        return -1 * self.ops.ts_rank(self.ops.rank(self.low), 9)
    
    def alpha006(self) -> pd.Series:
        """
        Alpha#6: 开盘-成交量相关性
        
        (-1 * correlation(open, volume, 10))
        
        思想：开盘价与成交量的相关性（反转信号）
        """
        return -1 * self.ops.ts_corr(self.open, self.volume, 10)
    
    def alpha007(self) -> pd.Series:
        """
        Alpha#7: 振幅-成交量相关性条件因子
        
        ((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : (-1 * 1))
        
        思想：当成交量大于20日均量时，看7日价格变化的排名
        """
        adv20 = self.ops.ts_mean(self.volume, 20)
        delta_close = self.ops.ts_delta(self.close, 7)
        rank_abs_delta = self.ops.ts_rank(np.abs(delta_close), 60)
        
        result = -1 * rank_abs_delta * self.ops.sign(delta_close)
        result[adv20 >= self.volume] = -1
        return result
    
    def alpha008(self) -> pd.Series:
        """
        Alpha#8: 延迟反转因子
        
        (-1 * rank(((sum(open, 5) * sum(returns, 5)) - delay((sum(open, 5) * sum(returns, 5)), 10))))
        
        思想：近期开盘价与收益的乘积对10天前的变化
        """
        sum_open = self.ops.ts_sum(self.open, 5)
        sum_returns = self.ops.ts_sum(self.returns, 5)
        prod = sum_open * sum_returns
        
        return -1 * self.ops.rank(prod - prod.shift(10))
    
    def alpha009(self) -> pd.Series:
        """
        Alpha#9: 收盘价变化条件因子
        
        ((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : ((ts_max(delta(close, 1), 5) < 0) ? delta(close, 1) : (-1 * delta(close, 1))))
        
        思想：根据5天内价格变化的趋势决定信号方向
        """
        delta = self.ops.ts_delta(self.close, 1)
        min_delta = self.ops.ts_min(delta, 5)
        max_delta = self.ops.ts_max(delta, 5)
        
        result = -1 * delta
        result[min_delta > 0] = delta[min_delta > 0]
        result[(min_delta <= 0) & (max_delta < 0)] = delta[(min_delta <= 0) & (max_delta < 0)]
        
        return result
    
    def alpha010(self) -> pd.Series:
        """
        Alpha#10: 收盘价变化排名因子
        
        rank(((0 < ts_min(delta(close, 1), 4)) ? delta(close, 1) : ((ts_max(delta(close, 1), 4) < 0) ? delta(close, 1) : (-1 * delta(close, 1)))))
        
        思想：类似Alpha9，但取排名
        """
        delta = self.ops.ts_delta(self.close, 1)
        min_delta = self.ops.ts_min(delta, 4)
        max_delta = self.ops.ts_max(delta, 4)
        
        result = -1 * delta
        result[min_delta > 0] = delta[min_delta > 0]
        result[(min_delta <= 0) & (max_delta < 0)] = delta[(min_delta <= 0) & (max_delta < 0)]
        
        return self.ops.rank(result)
    
    def alpha012(self) -> pd.Series:
        """
        Alpha#12: 成交量加权价格动量
        
        (sign(delta(volume, 1)) * (-1 * delta(close, 1)))
        
        思想：成交量增加时价格下跌（反转）
        """
        return self.ops.sign(self.ops.ts_delta(self.volume, 1)) * (-1 * self.ops.ts_delta(self.close, 1))
    
    # ============================================================
    # 量价关系类因子（10个）
    # ============================================================
    
    def alpha013(self) -> pd.Series:
        """
        Alpha#13: 收盘价-成交量协方差
        
        (-1 * rank(covariance(rank(close), rank(volume), 5)))
        
        思想：价量协方差的反转
        """
        return -1 * self.ops.rank(
            self.ops.ts_cov(
                self.ops.rank(self.close),
                self.ops.rank(self.volume),
                5
            )
        )
    
    def alpha014(self) -> pd.Series:
        """
        Alpha#14: 收益-成交量反相关
        
        ((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10))
        
        思想：收益变化与开盘价-成交量相关性
        """
        return (-1 * self.ops.rank(self.ops.ts_delta(self.returns, 3))) * \
               self.ops.ts_corr(self.open, self.volume, 10)
    
    def alpha015(self) -> pd.Series:
        """
        Alpha#15: 高价-成交量相关性
        
        (-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))
        
        思想：高价与成交量相关性的累积
        """
        corr = self.ops.ts_corr(
            self.ops.rank(self.high),
            self.ops.rank(self.volume),
            3
        )
        return -1 * self.ops.ts_sum(self.ops.rank(corr), 3)
    
    def alpha016(self) -> pd.Series:
        """
        Alpha#16: 高价排名因子
        
        (-1 * rank(covariance(rank(high), rank(volume), 5)))
        
        思想：高价与成交量协方差
        """
        return -1 * self.ops.rank(
            self.ops.ts_cov(
                self.ops.rank(self.high),
                self.ops.rank(self.volume),
                5
            )
        )
    
    def alpha017(self) -> pd.Series:
        """
        Alpha#17: VWAP-收盘价关系
        
        (((-1 * rank(ts_rank(close, 10))) * rank(delta(delta(close, 1), 1))) * rank(ts_rank((volume / adv20), 5)))
        
        思想：价格排名 × 加速度 × 成交量排名
        """
        adv20 = self.ops.ts_mean(self.volume, 20)
        
        part1 = -1 * self.ops.rank(self.ops.ts_rank(self.close, 10))
        part2 = self.ops.rank(self.ops.ts_delta(self.ops.ts_delta(self.close, 1), 1))
        part3 = self.ops.rank(self.ops.ts_rank(self.volume / (adv20 + 1e-8), 5))
        
        return part1 * part2 * part3
    
    def alpha018(self) -> pd.Series:
        """
        Alpha#18: 收盘价自相关
        
        (-1 * rank(((stddev(abs((close - open)), 5) + (close - open)) + correlation(close, open, 10))))
        
        思想：振幅标准差 + 涨跌幅 + 开收相关性
        """
        part1 = self.ops.ts_std(np.abs(self.close - self.open), 5)
        part2 = self.close - self.open
        part3 = self.ops.ts_corr(self.close, self.open, 10)
        
        return -1 * self.ops.rank(part1 + part2 + part3)
    
    def alpha019(self) -> pd.Series:
        """
        Alpha#19: 收盘价变化反转
        
        ((-1 * sign(((close - delay(close, 7)) + delta(close, 7)))) * (1 + rank((1 + sum(returns, 250)))))
        
        思想：7日价格变化的符号 × 250日累积收益排名
        """
        part1 = -1 * self.ops.sign(
            (self.close - self.close.shift(7)) + self.ops.ts_delta(self.close, 7)
        )
        part2 = 1 + self.ops.rank(1 + self.ops.ts_sum(self.returns, 250))
        
        return part1 * part2
    
    def alpha020(self) -> pd.Series:
        """
        Alpha#20: 开高低收排名因子
        
        (((-1 * rank((open - delay(high, 1)))) * rank((open - delay(close, 1)))) * rank((open - delay(low, 1))))
        
        思想：开盘价与前一日高/收/低的关系
        """
        part1 = -1 * self.ops.rank(self.open - self.high.shift(1))
        part2 = self.ops.rank(self.open - self.close.shift(1))
        part3 = self.ops.rank(self.open - self.low.shift(1))
        
        return part1 * part2 * part3
    
    def alpha021(self) -> pd.Series:
        """
        Alpha#21: 线性回归趋势因子
        
        ((((sum(close, 8) / 8) + stddev(close, 8)) < (sum(close, 2) / 2)) ? (-1 * 1) : 
         (((sum(close, 2) / 2) < ((sum(close, 8) / 8) - stddev(close, 8))) ? 1 : 
          (((1 < (volume / adv20)) || ((volume / adv20) == 1)) ? 1 : (-1 * 1))))
        
        思想：价格趋势与成交量的综合判断
        """
        sum8 = self.ops.ts_mean(self.close, 8)
        std8 = self.ops.ts_std(self.close, 8)
        sum2 = self.ops.ts_mean(self.close, 2)
        adv20 = self.ops.ts_mean(self.volume, 20)
        vol_ratio = self.volume / (adv20 + 1e-8)
        
        result = pd.Series(1.0, index=self.close.index)
        result[(sum8 + std8) < sum2] = -1
        result[sum2 < (sum8 - std8)] = 1
        result[vol_ratio >= 1] = 1
        
        return result
    
    def alpha022(self) -> pd.Series:
        """
        Alpha#22: 高价相关性因子
        
        (-1 * (delta(correlation(high, volume, 5), 5) * rank(stddev(close, 20))))
        
        思想：高价-成交量相关性的变化 × 价格波动率排名
        """
        corr = self.ops.ts_corr(self.high, self.volume, 5)
        delta_corr = self.ops.ts_delta(corr, 5)
        std_rank = self.ops.rank(self.ops.ts_std(self.close, 20))
        
        return -1 * delta_corr * std_rank
    
    # ============================================================
    # 波动率/风险类因子（5个）
    # ============================================================
    
    def alpha023(self) -> pd.Series:
        """
        Alpha#23: 下跌趋势因子
        
        (((sum(high, 20) / 20) < high) ? (-1 * delta(high, 2)) : 0)
        
        思想：当价格高于20日均价时，看2日高价变化
        """
        mean_high = self.ops.ts_mean(self.high, 20)
        delta_high = self.ops.ts_delta(self.high, 2)
        
        result = pd.Series(0.0, index=self.high.index)
        result[mean_high < self.high] = -1 * delta_high[mean_high < self.high]
        
        return result
    
    def alpha024(self) -> pd.Series:
        """
        Alpha#24: 收盘价趋势因子
        
        ((((delta((sum(close, 100) / 100), 100) / delay(close, 100)) < 0.05) ||
          ((delta((sum(close, 100) / 100), 100) / delay(close, 100)) == 0.05)) ? 
         (-1 * (close - ts_min(close, 100))) : (-1 * delta(close, 3)))
        
        思想：100日均线变化 < 5%时，看距离最低点的距离
        """
        mean100 = self.ops.ts_mean(self.close, 100)
        delta_mean = self.ops.ts_delta(mean100, 100)
        pct_change = delta_mean / (self.close.shift(100) + 1e-8)
        
        min100 = self.ops.ts_min(self.close, 100)
        delta3 = self.ops.ts_delta(self.close, 3)
        
        result = -1 * delta3
        result[pct_change <= 0.05] = -1 * (self.close - min100)[pct_change <= 0.05]
        
        return result
    
    def alpha026(self) -> pd.Series:
        """
        Alpha#26: 成交量相关性因子
        
        (-1 * ts_max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))
        
        思想：成交量排名与高价排名的相关性最大值
        """
        corr = self.ops.ts_corr(
            self.ops.ts_rank(self.volume, 5),
            self.ops.ts_rank(self.high, 5),
            5
        )
        return -1 * self.ops.ts_max(corr, 3)
    
    def alpha028(self) -> pd.Series:
        """
        Alpha#28: 量价相关性因子
        
        scale(((correlation(adv20, low, 5) + ((high + low) / 2)) - close))
        
        思想：成交量与低价相关性 + 中间价 - 收盘价
        """
        adv20 = self.ops.ts_mean(self.volume, 20)
        corr = self.ops.ts_corr(adv20, self.low, 5)
        mid_price = (self.high + self.low) / 2
        
        return self.ops.scale(corr + mid_price - self.close)
    
    def alpha029(self) -> pd.Series:
        """
        Alpha#29: 延迟收益因子
        
        (min(product(rank(rank(scale(log(sum(ts_min(rank(rank((-1 * rank(delta((close - 1), 5))))), 2), 1))))), 1), 5) +
         ts_rank(delay((-1 * returns), 6), 5))
        
        思想：复杂的价格变化排名 + 延迟收益排名
        """
        delta_close = self.ops.ts_delta(self.close - 1, 5)
        rank1 = self.ops.rank(-1 * self.ops.rank(delta_close))
        rank2 = self.ops.rank(self.ops.rank(rank1))
        ts_min_val = self.ops.ts_min(rank2, 2)
        
        sum_val = self.ops.ts_sum(ts_min_val, 1)
        log_val = np.log(sum_val + 1)
        scaled = self.ops.scale(log_val)
        
        part1 = self.ops.rank(self.ops.rank(scaled))
        part2 = self.ops.ts_rank((-1 * self.returns).shift(6), 5)
        
        return part1 + part2
    
    # ============================================================
    # 技术形态类因子（5个）
    # ============================================================
    
    def alpha030(self) -> pd.Series:
        """
        Alpha#30: 价格-成交量关系
        
        (((1.0 - rank(((sign((close - delay(close, 1))) + sign((delay(close, 1) - delay(close, 2)))) + 
         sign((delay(close, 2) - delay(close, 3)))))) * sum(volume, 5)) / sum(volume, 20))
        
        思想：连续3日价格变化符号 × 成交量比率
        """
        sign1 = self.ops.sign(self.close - self.close.shift(1))
        sign2 = self.ops.sign(self.close.shift(1) - self.close.shift(2))
        sign3 = self.ops.sign(self.close.shift(2) - self.close.shift(3))
        
        signs_sum = sign1 + sign2 + sign3
        part1 = 1.0 - self.ops.rank(signs_sum)
        
        vol_ratio = self.ops.ts_sum(self.volume, 5) / (self.ops.ts_sum(self.volume, 20) + 1e-8)
        
        return part1 * vol_ratio
    
    def alpha033(self) -> pd.Series:
        """
        Alpha#33: 开盘价排名因子
        
        rank((-1 * ((1 - (open / close))^1)))
        
        思想：开盘价与收盘价的比率排名
        """
        return self.ops.rank(-1 * (1 - self.open / (self.close + 1e-8)))
    
    def alpha034(self) -> pd.Series:
        """
        Alpha#34: 收益率-波动率比率
        
        rank(((1 - rank((stddev(returns, 2) / stddev(returns, 5)))) + (1 - rank(delta(close, 1)))))
        
        思想：短期波动率/长期波动率 + 价格变化
        """
        std2 = self.ops.ts_std(self.returns, 2)
        std5 = self.ops.ts_std(self.returns, 5)
        std_ratio = std2 / (std5 + 1e-8)
        
        part1 = 1 - self.ops.rank(std_ratio)
        part2 = 1 - self.ops.rank(self.ops.ts_delta(self.close, 1))
        
        return self.ops.rank(part1 + part2)
    
    def alpha037(self) -> pd.Series:
        """
        Alpha#37: 开盘价变化因子
        
        (rank(correlation(delay((open - close), 1), close, 200)) + rank((open - close)))
        
        思想：前日涨跌幅与收盘价的相关性 + 当日涨跌幅排名
        """
        open_close_diff = self.open - self.close
        delayed_diff = open_close_diff.shift(1)
        
        corr = self.ops.ts_corr(delayed_diff, self.close, 200)
        
        return self.ops.rank(corr) + self.ops.rank(open_close_diff)
    
    def alpha038(self) -> pd.Series:
        """
        Alpha#38: 高价排名因子
        
        ((-1 * rank(Ts_Rank(close, 10))) * rank((close / open)))
        
        思想：收盘价时间排名 × 涨跌幅排名
        """
        part1 = -1 * self.ops.rank(self.ops.ts_rank(self.close, 10))
        part2 = self.ops.rank(self.close / (self.open + 1e-8))
        
        return part1 * part2
    
    # ============================================================
    # 批量计算接口
    # ============================================================
    
    def calculate_all(self) -> pd.DataFrame:
        """
        计算所有30个Alpha101因子
        
        Returns
        -------
        pd.DataFrame
            包含所有因子的DataFrame，列名为'alpha_001', 'alpha_002', ...
        """
        result = pd.DataFrame(index=self.data.index)
        
        # 动量/反转类（10个）
        result['alpha_001'] = self.alpha001()
        result['alpha_002'] = self.alpha002()
        result['alpha_003'] = self.alpha003()
        result['alpha_004'] = self.alpha004()
        result['alpha_006'] = self.alpha006()
        result['alpha_007'] = self.alpha007()
        result['alpha_008'] = self.alpha008()
        result['alpha_009'] = self.alpha009()
        result['alpha_010'] = self.alpha010()
        result['alpha_012'] = self.alpha012()
        
        # 量价关系类（10个）
        result['alpha_013'] = self.alpha013()
        result['alpha_014'] = self.alpha014()
        result['alpha_015'] = self.alpha015()
        result['alpha_016'] = self.alpha016()
        result['alpha_017'] = self.alpha017()
        result['alpha_018'] = self.alpha018()
        result['alpha_019'] = self.alpha019()
        result['alpha_020'] = self.alpha020()
        result['alpha_021'] = self.alpha021()
        result['alpha_022'] = self.alpha022()
        
        # 波动率/风险类（5个）
        result['alpha_023'] = self.alpha023()
        result['alpha_024'] = self.alpha024()
        result['alpha_026'] = self.alpha026()
        result['alpha_028'] = self.alpha028()
        result['alpha_029'] = self.alpha029()
        
        # 技术形态类（5个）
        result['alpha_030'] = self.alpha030()
        result['alpha_033'] = self.alpha033()
        result['alpha_034'] = self.alpha034()
        result['alpha_037'] = self.alpha037()
        result['alpha_038'] = self.alpha038()
        
        # 添加日期和代码列（如果存在）
        if 'date' in self.data.columns:
            result['date'] = self.data['date'].values
        if 'ts_code' in self.data.columns:
            result['ts_code'] = self.data['ts_code'].values
        
        return result
    
    def calculate_selected(self, alpha_list: list) -> pd.DataFrame:
        """
        计算指定的Alpha101因子
        
        Parameters
        ----------
        alpha_list : list
            因子编号列表，如[1, 2, 3, 6, 7]
        
        Returns
        -------
        pd.DataFrame
            包含指定因子的DataFrame
        """
        result = pd.DataFrame(index=self.data.index)
        
        for alpha_num in alpha_list:
            method_name = f'alpha{alpha_num:03d}'
            if hasattr(self, method_name):
                result[f'alpha_{alpha_num:03d}'] = getattr(self, method_name)()
            else:
                print(f"Warning: {method_name} not implemented")
        
        # 添加日期和代码列（如果存在）
        if 'date' in self.data.columns:
            result['date'] = self.data['date'].values
        if 'ts_code' in self.data.columns:
            result['ts_code'] = self.data['ts_code'].values
        
        return result


def calculate_alpha101_for_stock(csv_file: str, alpha_list: Optional[list] = None) -> pd.DataFrame:
    """
    为单只股票计算Alpha101因子
    
    Parameters
    ----------
    csv_file : str
        股票数据CSV文件路径
    alpha_list : list, optional
        要计算的因子编号列表。如果为None，计算所有30个因子
    
    Returns
    -------
    pd.DataFrame
        包含因子值的DataFrame
    """
    # 读取数据
    data = pd.read_csv(csv_file)
    data.columns = data.columns.str.lower()
    
    # 确保包含必要的列
    required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
    if not all(col in data.columns for col in required_cols):
        raise ValueError(f"CSV file must contain columns: {required_cols}")
    
    # 计算因子
    alpha = Alpha101Factors(data)
    
    if alpha_list is None:
        result = alpha.calculate_all()
    else:
        result = alpha.calculate_selected(alpha_list)
    
    return result


if __name__ == "__main__":
    # 测试代码
    import sys
    
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
        
        print(f"计算 {csv_file} 的Alpha101因子...")
        
        # 计算所有因子
        factors = calculate_alpha101_for_stock(csv_file)
        
        print(f"\n因子计算完成！")
        print(f"因子数量: {len([col for col in factors.columns if col.startswith('alpha_')])}")
        print(f"数据行数: {len(factors)}")
        print(f"\n前5行数据:")
        print(factors.head())
        
        print(f"\n因子统计:")
        print(factors.describe())
    else:
        print("用法: python alpha101_factors.py <csv_file>")
        print("示例: python alpha101_factors.py data/000001.csv")


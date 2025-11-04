"""
Alpha因子整合模块
==================
整合开源的Alpha101和Alpha191因子库

本模块将您下载的开源因子库与项目整合，提供统一接口
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from typing import Optional, List

# 添加开源alpha库到路径
ALPHAS_PATH = Path('/home/yang/projects/alphas')
if ALPHAS_PATH.exists():
    sys.path.insert(0, str(ALPHAS_PATH))
    
    try:
        from alphas101 import Alphas101
        from alphas191 import Alphas191
        ALPHAS_AVAILABLE = True
    except ImportError:
        ALPHAS_AVAILABLE = False
        print("Warning: Open-source alpha libraries not available")
else:
    ALPHAS_AVAILABLE = False


class AlphaIntegration:
    """
    Alpha因子整合器
    
    整合开源alpha101/191与本项目的因子计算
    """
    
    def __init__(self, data: pd.DataFrame):
        """
        初始化
        
        Parameters
        ----------
        data : pd.DataFrame
            股票数据，需包含列：['date', 'open', 'high', 'low', 'close', 'volume']
        """
        self.data = data.copy()
        
        # 确保有必要的列
        required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in self.data.columns for col in required_cols):
            raise ValueError(f"Data must contain columns: {required_cols}")
        
        # 准备数据格式（转换为宽表格式，适配开源库）
        self.pivot_data = self._prepare_pivot_format()
    
    def _prepare_pivot_format(self) -> Optional[pd.DataFrame]:
        """
        准备透视表格式的数据
        
        开源库需要的格式：index=date, columns=asset, values=price
        """
        if not ALPHAS_AVAILABLE:
            return None
        
        # 简化：对于单股票，创建一个dummy的透视表
        if 'asset' not in self.data.columns:
            self.data['asset'] = 'stock'
        
        try:
            pivot_data = self.data.pivot(index='date', columns='asset')
            return pivot_data
        except Exception as e:
            print(f"Warning: Failed to create pivot format: {e}")
            return None
    
    def calculate_alpha101_selected(self, alpha_list: Optional[List[int]] = None) -> pd.DataFrame:
        """
        计算选定的Alpha101因子
        
        Parameters
        ----------
        alpha_list : list, optional
            要计算的因子编号列表。如果为None，计算前30个
        
        Returns
        -------
        pd.DataFrame
            因子值
        """
        if not ALPHAS_AVAILABLE or self.pivot_data is None:
            print("Warning: Using fallback implementation")
            return self._calculate_alpha101_fallback(alpha_list)
        
        # 使用开源库计算
        try:
            alpha101 = Alphas101(self.pivot_data)
            
            if alpha_list is None:
                alpha_list = list(range(1, 31))  # 前30个
            
            results = {}
            for alpha_num in alpha_list:
                method_name = f'alpha{alpha_num:03d}'
                if hasattr(alpha101, method_name):
                    try:
                        factor_val = getattr(alpha101, method_name)()
                        results[f'alpha101_{alpha_num:03d}'] = factor_val
                    except Exception as e:
                        print(f"Warning: Failed to calculate {method_name}: {e}")
            
            if results:
                result_df = pd.DataFrame(results)
                result_df['date'] = self.data['date'].values
                return result_df
            else:
                return pd.DataFrame()
        
        except Exception as e:
            print(f"Error calculating Alpha101: {e}")
            return self._calculate_alpha101_fallback(alpha_list)
    
    def _calculate_alpha101_fallback(self, alpha_list: Optional[List[int]] = None) -> pd.DataFrame:
        """
        Alpha101的降级实现（使用本项目的实现）
        """
        from factor_lib.alpha101_factors import Alpha101Factors
        
        alpha = Alpha101Factors(self.data)
        
        if alpha_list is None:
            # 计算所有30个因子
            return alpha.calculate_all()
        else:
            # 计算选定的因子
            return alpha.calculate_selected(alpha_list)
    
    def calculate_alpha191_selected(self, alpha_list: Optional[List[int]] = None) -> pd.DataFrame:
        """
        计算选定的Alpha191因子
        
        Parameters
        ----------
        alpha_list : list, optional
            要计算的因子编号列表。如果为None，计算常用的50个
        
        Returns
        -------
        pd.DataFrame
            因子值
        """
        if not ALPHAS_AVAILABLE or self.pivot_data is None:
            print("Warning: Alpha191 not available, skipping")
            return pd.DataFrame()
        
        try:
            alpha191 = Alphas191(self.pivot_data)
            
            if alpha_list is None:
                # 选择常用的50个因子
                alpha_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                             11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
                             21, 22, 23, 24, 25, 26, 27, 28, 29, 30,
                             31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
                             41, 42, 43, 44, 45, 46, 47, 48, 49, 50]
            
            results = {}
            for alpha_num in alpha_list:
                method_name = f'alpha{alpha_num:03d}'
                if hasattr(alpha191, method_name):
                    try:
                        factor_val = getattr(alpha191, method_name)()
                        results[f'alpha191_{alpha_num:03d}'] = factor_val
                    except Exception as e:
                        print(f"Warning: Failed to calculate {method_name}: {e}")
            
            if results:
                result_df = pd.DataFrame(results)
                result_df['date'] = self.data['date'].values
                return result_df
            else:
                return pd.DataFrame()
        
        except Exception as e:
            print(f"Error calculating Alpha191: {e}")
            return pd.DataFrame()
    
    def compare_implementations(self, alpha_nums: List[int] = [1, 2, 3, 4, 6]) -> pd.DataFrame:
        """
        对比本项目实现和开源实现的一致性
        
        Parameters
        ----------
        alpha_nums : list
            要对比的因子编号
        
        Returns
        -------
        pd.DataFrame
            对比结果
        """
        print("=" * 60)
        print("Alpha101 实现对比")
        print("=" * 60)
        
        # 本项目实现
        our_impl = self._calculate_alpha101_fallback(alpha_nums)
        
        # 开源实现
        if ALPHAS_AVAILABLE:
            open_source_impl = self.calculate_alpha101_selected(alpha_nums)
        else:
            print("Open-source implementation not available")
            return pd.DataFrame()
        
        # 对比
        comparison = []
        for alpha_num in alpha_nums:
            our_col = f'alpha_{alpha_num:03d}'
            os_col = f'alpha101_{alpha_num:03d}'
            
            if our_col in our_impl.columns and os_col in open_source_impl.columns:
                our_vals = our_impl[our_col].dropna()
                os_vals = open_source_impl[os_col].dropna()
                
                # 计算相关性
                if len(our_vals) > 0 and len(os_vals) > 0:
                    # 取两者的交集
                    min_len = min(len(our_vals), len(os_vals))
                    correlation = np.corrcoef(our_vals[:min_len], os_vals[:min_len])[0, 1]
                    
                    comparison.append({
                        'alpha': alpha_num,
                        'our_mean': our_vals.mean(),
                        'os_mean': os_vals.mean(),
                        'our_std': our_vals.std(),
                        'os_std': os_vals.std(),
                        'correlation': correlation,
                        'match': 'High' if correlation > 0.9 else ('Medium' if correlation > 0.7 else 'Low')
                    })
        
        comparison_df = pd.DataFrame(comparison)
        
        print("\n对比结果:")
        print(comparison_df.to_string(index=False))
        
        return comparison_df


def calculate_integrated_alphas(
    csv_file: str,
    use_open_source: bool = True,
    alpha101_list: Optional[List[int]] = None,
    alpha191_list: Optional[List[int]] = None
) -> pd.DataFrame:
    """
    计算整合的Alpha因子
    
    Parameters
    ----------
    csv_file : str
        股票数据CSV文件
    use_open_source : bool
        是否优先使用开源实现
    alpha101_list : list, optional
        Alpha101因子列表
    alpha191_list : list, optional
        Alpha191因子列表
    
    Returns
    -------
    pd.DataFrame
        所有因子
    """
    # 读取数据
    data = pd.read_csv(csv_file)
    data.columns = data.columns.str.lower()
    
    # 初始化整合器
    integrator = AlphaIntegration(data)
    
    results = pd.DataFrame()
    results['date'] = data['date']
    
    # 计算Alpha101
    print("计算Alpha101因子...")
    if use_open_source and ALPHAS_AVAILABLE:
        alpha101 = integrator.calculate_alpha101_selected(alpha101_list)
    else:
        alpha101 = integrator._calculate_alpha101_fallback(alpha101_list)
    
    if not alpha101.empty:
        results = results.merge(alpha101, on='date', how='left')
    
    # 计算Alpha191
    if alpha191_list:
        print("计算Alpha191因子...")
        alpha191 = integrator.calculate_alpha191_selected(alpha191_list)
        if not alpha191.empty:
            results = results.merge(alpha191, on='date', how='left')
    
    print(f"完成！计算了 {len(results.columns)-1} 个因子")
    
    return results


if __name__ == "__main__":
    # 测试代码
    import sys
    
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
        
        print(f"测试文件: {csv_file}")
        print(f"开源库可用: {ALPHAS_AVAILABLE}")
        
        # 测试因子计算
        factors = calculate_integrated_alphas(
            csv_file,
            use_open_source=True,
            alpha101_list=[1, 2, 3, 4, 6, 7, 8, 9, 10],  # 测试前10个
            alpha191_list=None  # 不计算alpha191
        )
        
        print(f"\n因子统计:")
        print(factors.describe())
        
        # 如果开源库可用，进行对比测试
        if ALPHAS_AVAILABLE:
            data = pd.read_csv(csv_file)
            data.columns = data.columns.str.lower()
            integrator = AlphaIntegration(data)
            comparison = integrator.compare_implementations([1, 2, 3, 4, 6])
            
            print(f"\n实现对比结果已生成")
    
    else:
        print("用法: python alpha_integration.py <csv_file>")
        print("示例: python alpha_integration.py data/000001.csv")


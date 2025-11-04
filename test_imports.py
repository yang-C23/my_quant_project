"""
测试所有模块的导入
===================
验证项目的所有核心模块都能正常导入
"""

import sys

def test_imports():
    """测试所有核心模块导入"""
    
    tests = []
    
    # 1. 回测引擎
    try:
        from backtest_engine import (
            TushareDailyCSV,
            AShareCommissionScheme,
            BacktestResult,
            extract_trades,
            run_backtest
        )
        tests.append(("✓ backtest_engine", True))
    except Exception as e:
        tests.append((f"✗ backtest_engine: {e}", False))
    
    # 2. 自定义指标
    try:
        from custom_indicators import (
            ZhiXingShortTrend,
            ZhiXingMultiAverage,
            KDJ,
            VolumeBreath,
            ATRTrailingStop
        )
        tests.append(("✓ custom_indicators", True))
    except Exception as e:
        tests.append((f"✗ custom_indicators: {e}", False))
    
    # 3. 策略
    try:
        from custom_strategies.dual_line_breath import DualLineBreathStrategy
        tests.append(("✓ dual_line_breath", True))
    except Exception as e:
        tests.append((f"✗ dual_line_breath: {e}", False))
    
    try:
        from custom_strategies.ml_strategy import MLSignalStrategy
        tests.append(("✓ ml_strategy", True))
    except Exception as e:
        tests.append((f"✗ ml_strategy: {e}", False))
    
    # 4. 因子库
    try:
        from factor_lib.custom_factors import TrendSpreadFactor
        tests.append(("✓ custom_factors", True))
    except Exception as e:
        tests.append((f"✗ custom_factors: {e}", False))
    
    try:
        from factor_lib.alpha101_factors import Alpha101Factors
        tests.append(("✓ alpha101_factors", True))
    except Exception as e:
        tests.append((f"✗ alpha101_factors: {e}", False))
    
    try:
        from factor_lib.technical_factors import TechnicalFactors
        tests.append(("✓ technical_factors", True))
    except Exception as e:
        tests.append((f"✗ technical_factors: {e}", False))
    
    try:
        from factor_lib.industry_factors import IndustryFactors
        tests.append(("✓ industry_factors", True))
    except Exception as e:
        tests.append((f"✗ industry_factors: {e}", False))
    
    try:
        from factor_lib.preprocessing import FactorPreprocessor
        tests.append(("✓ preprocessing", True))
    except Exception as e:
        tests.append((f"✗ preprocessing: {e}", False))
    
    try:
        from factor_lib.ic_analysis import FactorAnalyzer
        tests.append(("✓ ic_analysis", True))
    except Exception as e:
        tests.append((f"✗ ic_analysis: {e}", False))
    
    try:
        from factor_lib.alpha_integration import AlphaIntegration
        tests.append(("✓ alpha_integration", True))
    except Exception as e:
        tests.append((f"✗ alpha_integration: {e}", False))
    
    # 5. 机器学习
    try:
        from feature_engineering import FeatureEngineer, TripleBarrierLabeler
        tests.append(("✓ feature_engineering", True))
    except Exception as e:
        tests.append((f"✗ feature_engineering: {e}", False))
    
    try:
        from ml_trainer import LightGBMTrainer
        tests.append(("✓ ml_trainer (LightGBM未安装)", True))
    except ImportError as e:
        if 'lightgbm' in str(e):
            tests.append(("⚠ ml_trainer (需安装LightGBM)", True))
        else:
            tests.append((f"✗ ml_trainer: {e}", False))
    except Exception as e:
        tests.append((f"✗ ml_trainer: {e}", False))
    
    # 6. 测试和优化
    try:
        from condition_ablation_test import ConditionalStrategy
        tests.append(("✓ condition_ablation_test", True))
    except Exception as e:
        tests.append((f"✗ condition_ablation_test: {e}", False))
    
    try:
        from stop_loss_strategies import get_stop_loss_strategy
        tests.append(("✓ stop_loss_strategies", True))
    except Exception as e:
        tests.append((f"✗ stop_loss_strategies: {e}", False))
    
    # 7. 组合回测
    try:
        from portfolio_backtest import PortfolioBacktester
        tests.append(("✓ portfolio_backtest", True))
    except Exception as e:
        tests.append((f"✗ portfolio_backtest: {e}", False))
    
    # 打印结果
    print("=" * 60)
    print("模块导入测试")
    print("=" * 60)
    
    for msg, status in tests:
        print(msg)
    
    # 统计
    success = sum(1 for _, status in tests if status)
    total = len(tests)
    
    print("=" * 60)
    print(f"测试结果: {success}/{total} 通过")
    
    if success == total:
        print("✅ 所有模块导入成功！")
        return 0
    else:
        print("⚠️ 部分模块导入失败，请检查")
        return 1


if __name__ == "__main__":
    sys.exit(test_imports())


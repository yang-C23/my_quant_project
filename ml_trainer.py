"""
机器学习训练器
================
LightGBM训练模块（支持GPU加速）

主要功能：
1. LightGBM模型训练（分类/回归）
2. GPU加速支持
3. 时间序列交叉验证
4. SHAP特征重要性分析
5. 模型评估和可视化
"""

import numpy as np
import pandas as pd
import lightgbm as lgb
from pathlib import Path
from typing import Tuple, Dict, Optional, List
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, classification_report,
    mean_squared_error, mean_absolute_error, r2_score
)
import joblib
import json
import matplotlib.pyplot as plt
import seaborn as sns
import warnings
warnings.filterwarnings('ignore')

# SHAP for feature importance
try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    print("Warning: SHAP not available. Install with: pip install shap")


class LightGBMTrainer:
    """
    LightGBM训练器
    
    支持分类和回归任务，GPU加速，时间序列CV
    """
    
    def __init__(
        self,
        task_type: str = 'classification',
        use_gpu: bool = True,
        random_state: int = 42
    ):
        """
        初始化训练器
        
        Parameters
        ----------
        task_type : str
            任务类型：'classification' 或 'regression'
        use_gpu : bool
            是否使用GPU加速
        random_state : int
            随机种子
        """
        self.task_type = task_type
        self.use_gpu = use_gpu
        self.random_state = random_state
        self.model = None
        self.feature_importance = None
        self.training_history = None
        
        # 默认参数
        self.default_params = self._get_default_params()
    
    def _get_default_params(self) -> Dict:
        """获取默认参数"""
        base_params = {
            'boosting_type': 'gbdt',
            'learning_rate': 0.05,
            'num_leaves': 31,
            'max_depth': -1,
            'min_data_in_leaf': 20,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'lambda_l1': 0.1,
            'lambda_l2': 0.1,
            'random_state': self.random_state,
            'verbose': -1,
            'n_jobs': -1
        }
        
        # GPU加速
        if self.use_gpu:
            base_params['device'] = 'gpu'
            base_params['gpu_platform_id'] = 0
            base_params['gpu_device_id'] = 0
        
        # 任务特定参数
        if self.task_type == 'classification':
            base_params['objective'] = 'multiclass'
            base_params['metric'] = ['multi_logloss', 'multi_error']
            base_params['num_class'] = 3  # -1, 0, 1
        else:
            base_params['objective'] = 'regression'
            base_params['metric'] = ['l2', 'l1']
        
        return base_params
    
    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        params: Optional[Dict] = None,
        num_boost_round: int = 1000,
        early_stopping_rounds: int = 50
    ) -> Dict:
        """
        训练模型
        
        Parameters
        ----------
        X_train : pd.DataFrame
            训练特征
        y_train : pd.Series
            训练标签
        X_val : pd.DataFrame, optional
            验证特征
        y_val : pd.Series, optional
            验证标签
        params : dict, optional
            自定义参数（会覆盖默认参数）
        num_boost_round : int
            最大迭代次数
        early_stopping_rounds : int
            早停轮数
        
        Returns
        -------
        Dict
            训练历史
        """
        print("=" * 60)
        print("开始训练LightGBM模型")
        print("=" * 60)
        
        # 合并参数
        final_params = self.default_params.copy()
        if params:
            final_params.update(params)
        
        print(f"\n模型参数:")
        for k, v in final_params.items():
            print(f"  {k}: {v}")
        
        # 处理标签（分类任务需要从0开始）
        if self.task_type == 'classification':
            # 将-1, 0, 1 映射到 0, 1, 2
            label_mapping = {-1: 0, 0: 1, 1: 2}
            y_train_mapped = y_train.map(label_mapping)
            if y_val is not None:
                y_val_mapped = y_val.map(label_mapping)
        else:
            y_train_mapped = y_train
            y_val_mapped = y_val if y_val is not None else None
        
        # 创建LightGBM数据集
        train_data = lgb.Dataset(X_train, label=y_train_mapped)
        
        valid_sets = [train_data]
        valid_names = ['train']
        
        if X_val is not None and y_val is not None:
            val_data = lgb.Dataset(X_val, label=y_val_mapped, reference=train_data)
            valid_sets.append(val_data)
            valid_names.append('valid')
        
        # 训练模型
        print(f"\n开始训练...")
        print(f"训练样本数: {len(X_train)}")
        if X_val is not None:
            print(f"验证样本数: {len(X_val)}")
        
        evals_result = {}
        
        self.model = lgb.train(
            final_params,
            train_data,
            num_boost_round=num_boost_round,
            valid_sets=valid_sets,
            valid_names=valid_names,
            callbacks=[
                lgb.early_stopping(stopping_rounds=early_stopping_rounds),
                lgb.log_evaluation(period=50),
                lgb.record_evaluation(evals_result)
            ]
        )
        
        self.training_history = evals_result
        
        # 特征重要性
        self.feature_importance = pd.DataFrame({
            'feature': X_train.columns,
            'importance': self.model.feature_importance(importance_type='gain')
        }).sort_values('importance', ascending=False)
        
        print(f"\n训练完成！最佳迭代: {self.model.best_iteration}")
        print(f"\nTop 10 重要特征:")
        print(self.feature_importance.head(10))
        
        return evals_result
    
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        预测
        
        Parameters
        ----------
        X : pd.DataFrame
            特征
        
        Returns
        -------
        np.ndarray
            预测结果
        """
        if self.model is None:
            raise ValueError("Model not trained yet")
        
        if self.task_type == 'classification':
            # 返回类别概率
            pred_proba = self.model.predict(X, num_iteration=self.model.best_iteration)
            # 返回最大概率的类别
            pred = np.argmax(pred_proba, axis=1)
            
            # 映射回原始标签 -1, 0, 1
            label_mapping_inv = {0: -1, 1: 0, 2: 1}
            pred = np.array([label_mapping_inv[p] for p in pred])
            
            return pred
        else:
            return self.model.predict(X, num_iteration=self.model.best_iteration)
    
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        预测概率（仅分类任务）
        
        Parameters
        ----------
        X : pd.DataFrame
            特征
        
        Returns
        -------
        np.ndarray
            预测概率，shape=(n_samples, n_classes)
        """
        if self.task_type != 'classification':
            raise ValueError("predict_proba only available for classification")
        
        if self.model is None:
            raise ValueError("Model not trained yet")
        
        return self.model.predict(X, num_iteration=self.model.best_iteration)
    
    def evaluate(
        self,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        save_dir: Optional[str] = None
    ) -> Dict:
        """
        评估模型
        
        Parameters
        ----------
        X_test : pd.DataFrame
            测试特征
        y_test : pd.Series
            测试标签
        save_dir : str, optional
            保存目录
        
        Returns
        -------
        Dict
            评估指标
        """
        print("\n" + "=" * 60)
        print("模型评估")
        print("=" * 60)
        
        # 预测
        y_pred = self.predict(X_test)
        
        metrics = {}
        
        if self.task_type == 'classification':
            # 分类指标
            metrics['accuracy'] = accuracy_score(y_test, y_pred)
            metrics['precision'] = precision_score(y_test, y_pred, average='weighted', zero_division=0)
            metrics['recall'] = recall_score(y_test, y_pred, average='weighted', zero_division=0)
            metrics['f1'] = f1_score(y_test, y_pred, average='weighted', zero_division=0)
            
            print(f"\n准确率: {metrics['accuracy']:.4f}")
            print(f"精确率: {metrics['precision']:.4f}")
            print(f"召回率: {metrics['recall']:.4f}")
            print(f"F1分数: {metrics['f1']:.4f}")
            
            print(f"\n分类报告:")
            print(classification_report(y_test, y_pred, target_names=['Sell', 'Hold', 'Buy']))
            
            # 混淆矩阵
            cm = confusion_matrix(y_test, y_pred)
            metrics['confusion_matrix'] = cm.tolist()
            
            print(f"\n混淆矩阵:")
            print(cm)
            
            # 可视化混淆矩阵
            if save_dir:
                self._plot_confusion_matrix(cm, save_dir)
        
        else:
            # 回归指标
            metrics['mse'] = mean_squared_error(y_test, y_pred)
            metrics['rmse'] = np.sqrt(metrics['mse'])
            metrics['mae'] = mean_absolute_error(y_test, y_pred)
            metrics['r2'] = r2_score(y_test, y_pred)
            
            print(f"\nMSE: {metrics['mse']:.4f}")
            print(f"RMSE: {metrics['rmse']:.4f}")
            print(f"MAE: {metrics['mae']:.4f}")
            print(f"R²: {metrics['r2']:.4f}")
        
        # 保存评估结果
        if save_dir:
            save_path = Path(save_dir)
            save_path.mkdir(parents=True, exist_ok=True)
            
            with open(save_path / 'metrics.json', 'w') as f:
                json.dump(metrics, f, indent=2)
            
            print(f"\n评估结果已保存到: {save_dir}")
        
        return metrics
    
    def _plot_confusion_matrix(self, cm: np.ndarray, save_dir: str):
        """绘制混淆矩阵"""
        plt.figure(figsize=(8, 6))
        sns.heatmap(
            cm,
            annot=True,
            fmt='d',
            cmap='Blues',
            xticklabels=['Sell', 'Hold', 'Buy'],
            yticklabels=['Sell', 'Hold', 'Buy']
        )
        plt.title('Confusion Matrix')
        plt.ylabel('True Label')
        plt.xlabel('Predicted Label')
        plt.tight_layout()
        plt.savefig(Path(save_dir) / 'confusion_matrix.png', dpi=150)
        plt.close()
    
    def plot_training_history(self, save_path: Optional[str] = None):
        """绘制训练历史"""
        if self.training_history is None:
            print("No training history available")
            return
        
        fig, axes = plt.subplots(1, 2, figsize=(15, 5))
        
        # Loss曲线
        for dataset in self.training_history:
            if self.task_type == 'classification':
                metric_name = 'multi_logloss'
            else:
                metric_name = 'l2'
            
            if metric_name in self.training_history[dataset]:
                axes[0].plot(
                    self.training_history[dataset][metric_name],
                    label=f'{dataset} loss'
                )
        
        axes[0].set_xlabel('Iteration')
        axes[0].set_ylabel('Loss')
        axes[0].set_title('Training Loss')
        axes[0].legend()
        axes[0].grid(True)
        
        # Error曲线（分类）或MAE曲线（回归）
        for dataset in self.training_history:
            if self.task_type == 'classification':
                metric_name = 'multi_error'
            else:
                metric_name = 'l1'
            
            if metric_name in self.training_history[dataset]:
                axes[1].plot(
                    self.training_history[dataset][metric_name],
                    label=f'{dataset} error'
                )
        
        axes[1].set_xlabel('Iteration')
        axes[1].set_ylabel('Error' if self.task_type == 'classification' else 'MAE')
        axes[1].set_title('Training Error/MAE')
        axes[1].legend()
        axes[1].grid(True)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150)
            print(f"训练历史图已保存到: {save_path}")
        else:
            plt.show()
        
        plt.close()
    
    def plot_feature_importance(self, top_n: int = 20, save_path: Optional[str] = None):
        """绘制特征重要性"""
        if self.feature_importance is None:
            print("No feature importance available")
            return
        
        plt.figure(figsize=(10, max(8, top_n * 0.3)))
        
        top_features = self.feature_importance.head(top_n)
        
        plt.barh(range(len(top_features)), top_features['importance'])
        plt.yticks(range(len(top_features)), top_features['feature'])
        plt.xlabel('Importance (Gain)')
        plt.title(f'Top {top_n} Feature Importance')
        plt.gca().invert_yaxis()
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150)
            print(f"特征重要性图已保存到: {save_path}")
        else:
            plt.show()
        
        plt.close()
    
    def shap_analysis(
        self,
        X_sample: pd.DataFrame,
        save_dir: Optional[str] = None,
        max_display: int = 20
    ):
        """
        SHAP特征重要性分析
        
        Parameters
        ----------
        X_sample : pd.DataFrame
            用于SHAP分析的样本（建议<1000个样本）
        save_dir : str, optional
            保存目录
        max_display : int
            显示的最大特征数
        """
        if not SHAP_AVAILABLE:
            print("SHAP not available. Skipping...")
            return
        
        if self.model is None:
            print("Model not trained yet")
            return
        
        print("\n" + "=" * 60)
        print("SHAP特征重要性分析")
        print("=" * 60)
        
        # 创建SHAP explainer
        explainer = shap.TreeExplainer(self.model)
        
        # 计算SHAP值
        print(f"计算SHAP值 (样本数: {len(X_sample)})...")
        shap_values = explainer.shap_values(X_sample)
        
        # 对于多分类，取平均
        if isinstance(shap_values, list):
            shap_values_mean = np.abs(shap_values).mean(axis=0)
        else:
            shap_values_mean = np.abs(shap_values)
        
        # Summary plot
        plt.figure(figsize=(12, 8))
        shap.summary_plot(
            shap_values_mean,
            X_sample,
            max_display=max_display,
            show=False
        )
        
        if save_dir:
            save_path = Path(save_dir)
            save_path.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path / 'shap_summary.png', dpi=150, bbox_inches='tight')
            print(f"SHAP图已保存到: {save_dir}")
        else:
            plt.show()
        
        plt.close()
    
    def save_model(self, save_path: str):
        """保存模型"""
        if self.model is None:
            print("No model to save")
            return
        
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存LightGBM模型
        self.model.save_model(str(save_path))
        
        # 保存特征重要性
        if self.feature_importance is not None:
            self.feature_importance.to_csv(
                str(save_path).replace('.txt', '_feature_importance.csv'),
                index=False
            )
        
        print(f"模型已保存到: {save_path}")
    
    def load_model(self, load_path: str):
        """加载模型"""
        self.model = lgb.Booster(model_file=load_path)
        print(f"模型已从 {load_path} 加载")


def time_series_cv_train(
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 5,
    trainer_params: Optional[Dict] = None,
    train_params: Optional[Dict] = None,
    save_dir: Optional[str] = None
) -> Tuple[LightGBMTrainer, List[Dict]]:
    """
    时间序列交叉验证训练
    
    Parameters
    ----------
    X : pd.DataFrame
        特征
    y : pd.Series
        标签
    n_splits : int
        切分数量
    trainer_params : dict, optional
        训练器参数
    train_params : dict, optional
        训练参数
    save_dir : str, optional
        保存目录
    
    Returns
    -------
    Tuple[LightGBMTrainer, List[Dict]]
        (最终模型, CV评估结果列表)
    """
    from feature_engineering import time_series_split
    
    print("=" * 60)
    print(f"时间序列交叉验证训练 ({n_splits} folds)")
    print("=" * 60)
    
    # 初始化训练器
    trainer_params = trainer_params or {}
    trainer = LightGBMTrainer(**trainer_params)
    
    # 时间序列切分
    splits = time_series_split(X, y, n_splits=n_splits)
    
    cv_results = []
    
    for fold, (train_idx, test_idx) in enumerate(splits, 1):
        print(f"\n{'='*60}")
        print(f"Fold {fold}/{len(splits)}")
        print(f"{'='*60}")
        
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        
        print(f"训练集: {len(X_train)} 样本")
        print(f"测试集: {len(X_test)} 样本")
        
        # 训练
        train_params = train_params or {}
        trainer.train(X_train, y_train, **train_params)
        
        # 评估
        metrics = trainer.evaluate(X_test, y_test)
        metrics['fold'] = fold
        cv_results.append(metrics)
    
    # 汇总结果
    print(f"\n{'='*60}")
    print("交叉验证汇总")
    print(f"{'='*60}")
    
    if trainer.task_type == 'classification':
        avg_acc = np.mean([r['accuracy'] for r in cv_results])
        avg_f1 = np.mean([r['f1'] for r in cv_results])
        print(f"平均准确率: {avg_acc:.4f}")
        print(f"平均F1分数: {avg_f1:.4f}")
    else:
        avg_rmse = np.mean([r['rmse'] for r in cv_results])
        avg_r2 = np.mean([r['r2'] for r in cv_results])
        print(f"平均RMSE: {avg_rmse:.4f}")
        print(f"平均R²: {avg_r2:.4f}")
    
    # 保存结果
    if save_dir:
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)
        
        pd.DataFrame(cv_results).to_csv(save_path / 'cv_results.csv', index=False)
        print(f"\nCV结果已保存到: {save_dir}")
    
    return trainer, cv_results


if __name__ == "__main__":
    # 测试代码
    print("LightGBM训练器模块")
    print("请使用 feature_engineering.py 生成特征后，再使用此模块进行训练")

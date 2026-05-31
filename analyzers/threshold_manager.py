from typing import Dict, Any, Optional
from config.settings import MONITOR_CONFIG

class ThresholdManager:
    """阈值管理器"""
    
    def __init__(self):
        self.threshold_cache = {}
        self._build_threshold_cache()
    
    def _build_threshold_cache(self):
        """构建阈值缓存"""
        for frequency, asset_types in MONITOR_CONFIG.items():
            for asset_type, assets in asset_types.items():
                for asset in assets:
                    key = self._get_cache_key(asset['symbol'], asset.get('market', ''), frequency)
                    self.threshold_cache[key] = asset['threshold']
    
    def _get_cache_key(self, symbol: str, market: str, frequency: str) -> str:
        """获取缓存键"""
        return f"{symbol}_{market}_{frequency}"
    
    def get_threshold(self, symbol: str, frequency: str, market: str = "") -> float:
        """获取阈值"""
        key = self._get_cache_key(symbol, market, frequency)
        return self.threshold_cache.get(key, self._get_default_threshold(frequency))
    
    def _get_default_threshold(self, frequency: str) -> float:
        """获取默认阈值"""
        default_thresholds = {
            'minute': 2.0,
            'daily': 3.0,
            'weekly': 5.0
        }
        return default_thresholds.get(frequency, 2.0)
    
    def update_threshold(self, symbol: str, market: str, frequency: str, threshold: float):
        """更新阈值"""
        key = self._get_cache_key(symbol, market, frequency)
        self.threshold_cache[key] = threshold
    
    def get_all_thresholds(self) -> Dict[str, float]:
        """获取所有阈值"""
        return self.threshold_cache.copy()
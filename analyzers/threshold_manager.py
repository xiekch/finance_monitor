from typing import Dict, Any, Optional
from config.settings import MONITOR_CONFIG

class ThresholdManager:
    """阈值管理器（顺便托管 symbol -> 中文名 的查询）"""

    def __init__(self):
        self.threshold_cache: Dict[str, float] = {}
        # 按 (symbol, market) 索引中文名；不带 frequency，因为同一标的不同频率名字一致
        self.name_cache: Dict[str, str] = {}
        self._build_caches()

    def _build_caches(self):
        for frequency, asset_types in MONITOR_CONFIG.items():
            for asset_type, assets in asset_types.items():
                for asset in assets:
                    symbol = asset['symbol']
                    market = asset.get('market', '')
                    key = self._get_cache_key(symbol, market, frequency)
                    self.threshold_cache[key] = asset['threshold']
                    name = asset.get('name')
                    if name:
                        self.name_cache.setdefault(self._name_key(symbol, market), name)

    def _get_cache_key(self, symbol: str, market: str, frequency: str) -> str:
        return f"{symbol}_{market}_{frequency}"

    @staticmethod
    def _name_key(symbol: str, market: str) -> str:
        return f"{symbol}_{market}"

    def get_threshold(self, symbol: str, frequency: str, market: str = "") -> float:
        key = self._get_cache_key(symbol, market, frequency)
        return self.threshold_cache.get(key, self._get_default_threshold(frequency))

    def get_name(self, symbol: str, market: str = "") -> str:
        """返回标的中文名；配置里没有则 fallback 到 symbol。"""
        return self.name_cache.get(self._name_key(symbol, market), symbol)
    
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
from typing import Dict, Any, List, Optional
from config.minute_targets import minute_stock_targets
from config.monitor import MONITOR_CONFIG

class ThresholdManager:
    """阈值管理器（顺便托管 symbol -> 中文名 的查询）"""

    def __init__(self):
        self.threshold_cache: Dict[str, float] = {}
        # 按 (symbol, market) 索引中文名；不带 frequency，因为同一标的不同频率名字一致
        self.name_cache: Dict[str, str] = {}
        self._minute_stock_keys: set = set()  # 来自持仓的分钟级阈值 key，刷新时整体替换
        self._build_caches()

    def _build_caches(self):
        for asset_type, assets in MONITOR_CONFIG.items():
            for asset in assets:
                symbol = asset['symbol']
                market = asset.get('market', '')
                frequency = asset['frequency']
                key = self._get_cache_key(symbol, market, frequency)
                self.threshold_cache[key] = asset['threshold']
                if 'prev_close_threshold' in asset:
                    self.threshold_cache[
                        self._get_cache_key(symbol, market, 'prev_close')
                    ] = asset['prev_close_threshold']
                name = asset.get('name')
                if name:
                    self.name_cache.setdefault(self._name_key(symbol, market), name)

    def reload_minute_targets(self, targets: Optional[List[dict]] = None):
        """用持仓里的股票刷新分钟级阈值和名称。每轮分析前调用，持仓改了不用重启。"""
        if targets is None:
            targets = minute_stock_targets()
        for key in self._minute_stock_keys:
            self.threshold_cache.pop(key, None)
        self._minute_stock_keys = set()
        for asset in targets:
            symbol, market = asset['symbol'], asset.get('market', '')
            # minute：相对 N 分钟前；prev_close：相对昨收
            for frequency, field in (('minute', 'threshold'), ('prev_close', 'prev_close_threshold')):
                if field not in asset:
                    continue
                key = self._get_cache_key(symbol, market, frequency)
                self.threshold_cache[key] = asset[field]
                self._minute_stock_keys.add(key)
            self.name_cache.setdefault(self._name_key(symbol, market), asset['name'])

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
            'prev_close': 3.0,
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
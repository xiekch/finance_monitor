"""异步请求频控：同名 limiter 全局共享，串行且保证最小间隔。"""

from __future__ import annotations

import asyncio
import time
from typing import Dict


class AsyncRateLimiter:
    def __init__(self, min_interval_seconds: float):
        self.min_interval = max(0.0, float(min_interval_seconds))
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()


_LIMITERS: Dict[str, AsyncRateLimiter] = {}


def get_rate_limiter(name: str, min_interval_seconds: float) -> AsyncRateLimiter:
    limiter = _LIMITERS.get(name)
    if limiter is None:
        limiter = AsyncRateLimiter(min_interval_seconds)
        _LIMITERS[name] = limiter
    return limiter

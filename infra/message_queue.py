"""消息总线抽象 + 两种 backend。

默认 in-memory（个人监控、单进程足够）；
设置环境变量 ``MQ_BACKEND=redis`` 切回 Redis pub/sub（多进程/多主机场景）。
"""
import json
import logging
import queue
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Protocol


class MessageQueueBackend(Protocol):
    def publish(self, channel: str, message: Dict[str, Any]) -> None: ...
    def subscribe(self, channel: str, callback: Callable[[Dict[str, Any]], None]) -> None: ...
    # push_to_queue / pop_from_queue / get_queue_length 是原 Redis 实现保留的
    # "任务队列" 接口，目前代码库无引用；仅 RedisMessageQueue 保留实现。


class RedisMessageQueue:
    """基于 Redis Pub/Sub 的消息总线。跨进程 / 跨主机用。"""

    def __init__(self):
        import redis
        from config.settings import REDIS_CONFIG
        self.redis_client = redis.Redis(
            host=REDIS_CONFIG["host"],
            port=REDIS_CONFIG["port"],
            db=REDIS_CONFIG["db"],
            password=REDIS_CONFIG.get("password"),
            decode_responses=True,
        )

    def publish(self, channel: str, message: Dict[str, Any]) -> None:
        try:
            self.redis_client.publish(channel, json.dumps(message, default=str))
        except Exception as e:
            logging.error(f"[redis] publish failed channel={channel}: {e}")

    def subscribe(self, channel: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        """阻塞当前线程，订阅 channel 并把每条消息交给 callback。"""
        pubsub = self.redis_client.pubsub()

        def _handler(msg):
            if msg["type"] == "message":
                try:
                    callback(json.loads(msg["data"]))
                except Exception as e:
                    logging.error(f"[redis] handler error: {e}", exc_info=True)

        pubsub.subscribe(**{channel: _handler})
        logging.info(f"[redis] 开始监听频道: {channel}")
        for _ in pubsub.listen():
            pass

    # 任务队列接口（保留兼容，目前无调用方）
    def push_to_queue(self, queue_name: str, item: Dict[str, Any]) -> None:
        try:
            self.redis_client.lpush(queue_name, json.dumps(item, default=str))
        except Exception as e:
            logging.error(f"[redis] push_to_queue failed: {e}")

    def pop_from_queue(self, queue_name: str, timeout: int = 0) -> Optional[Dict[str, Any]]:
        try:
            if timeout > 0:
                result = self.redis_client.brpop(queue_name, timeout=timeout)
                if result:
                    _, item_data = result
                    return json.loads(item_data)
            else:
                item_data = self.redis_client.rpop(queue_name)
                if item_data:
                    return json.loads(item_data)
        except Exception as e:
            logging.error(f"[redis] pop_from_queue failed: {e}")
        return None

    def get_queue_length(self, queue_name: str) -> int:
        return self.redis_client.llen(queue_name)


class InMemoryMessageQueue:
    """进程内 fan-out pub/sub。

    与 Redis pub/sub 语义一致：每个 ``subscribe`` 调用占用当前线程并阻塞，
    每个订阅者拿到 publish 的完整一份消息（broadcast）。

    注意：队列无上限。极端情况下消费者卡死会让队列无界增长 → OOM。
    对个人监控、低频场景足够；如未来加高频源，需要补 maxsize + drop 策略。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._subscribers: Dict[str, List[queue.Queue]] = defaultdict(list)

    def publish(self, channel: str, message: Dict[str, Any]) -> None:
        with self._lock:
            queues = list(self._subscribers[channel])
        for q in queues:
            q.put(message)   # 立即返回，consumer 在各自线程消费

    def subscribe(self, channel: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers[channel].append(q)
        logging.info(f"[memory] 开始监听频道: {channel}")
        while True:
            msg = q.get()
            try:
                callback(msg)
            except Exception as e:
                logging.error(f"[memory] handler error: {e}", exc_info=True)


def _build_default_backend() -> MessageQueueBackend:
    from config.settings import MQ_BACKEND
    if MQ_BACKEND == "redis":
        logging.info("[mq] 使用 Redis backend (MQ_BACKEND=redis)")
        return RedisMessageQueue()
    if MQ_BACKEND != "memory":
        logging.warning(f"[mq] 未知 MQ_BACKEND={MQ_BACKEND!r}，回退到 memory")
    logging.info("[mq] 使用 InMemory backend (单进程)")
    return InMemoryMessageQueue()


# 全局消息队列实例
mq: MessageQueueBackend = _build_default_backend()

"""消息总线抽象 + 两种 backend。

默认 in-memory（个人监控、单进程足够）；
设置 ``MQ_BACKEND=redis`` 切回 Redis pub/sub（多进程/多主机场景）。

API 契约：publish/subscribe 都以 ``BaseMessage`` 对象交互；
序列化（如果有）是 backend 内部实现细节。
"""
import copy
import json
import logging
import queue
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Protocol

from models.messages import BaseMessage


class MessageQueueBackend(Protocol):
    def publish(self, channel: str, message: BaseMessage) -> None: ...
    def subscribe(self, channel: str, callback: Callable[[BaseMessage], None]) -> None: ...


class RedisMessageQueue:
    """基于 Redis Pub/Sub 的消息总线。跨进程 / 跨主机用。

    序列化：publish 时 to_dict + json.dumps；subscribe 时 json.loads + BaseMessage.deserialize。
    """

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

    def publish(self, channel: str, message: BaseMessage) -> None:
        try:
            self.redis_client.publish(
                channel, json.dumps(message.to_dict(), default=str)
            )
        except Exception as e:
            logging.error(f"[redis] publish failed channel={channel}: {e}")

    def subscribe(self, channel: str, callback: Callable[[BaseMessage], None]) -> None:
        """阻塞当前线程，订阅 channel 并把每条消息（已反序列化为 BaseMessage）交给 callback。"""
        pubsub = self.redis_client.pubsub()

        def _handler(msg):
            if msg["type"] == "message":
                try:
                    data = json.loads(msg["data"])
                    callback(BaseMessage.deserialize(data))
                except Exception as e:
                    logging.error(f"[redis] handler error: {e}", exc_info=True)

        pubsub.subscribe(**{channel: _handler})
        logging.info(f"[redis] 开始监听频道: {channel}")
        for _ in pubsub.listen():
            pass


class InMemoryMessageQueue:
    """进程内 fan-out pub/sub。

    与 Redis pub/sub 语义一致：每个 ``subscribe`` 调用占用当前线程并阻塞，
    每个订阅者拿到 publish 的完整一份消息（broadcast）。

    每个订阅者拿到独立 deepcopy，避免消费者改了对象影响其他消费者；
    匹配 Redis 路径的 json round-trip 隔离语义。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._subscribers: Dict[str, List[queue.Queue]] = defaultdict(list)

    def publish(self, channel: str, message: BaseMessage) -> None:
        with self._lock:
            queues = list(self._subscribers[channel])
        for q in queues:
            q.put(copy.deepcopy(message))

    def subscribe(self, channel: str, callback: Callable[[BaseMessage], None]) -> None:
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

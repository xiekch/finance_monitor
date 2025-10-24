import redis
import json
import pickle
import logging
from typing import Any, Dict, Optional
from config.settings import REDIS_CONFIG

class MessageQueue:
    """基于Redis的消息队列"""
    
    def __init__(self):
        self.redis_client = redis.Redis(
            host=REDIS_CONFIG['host'],
            port=REDIS_CONFIG['port'],
            db=REDIS_CONFIG['db'],
            password=REDIS_CONFIG.get('password'),
            decode_responses=True
        )
    
    def publish(self, channel: str, message: Dict[str, Any]):
        """发布消息到指定频道"""
        try:
            serialized_message = json.dumps(message, default=str)
            self.redis_client.publish(channel, serialized_message)
        except Exception as e:
            print(f"消息发布失败: {e}")
    
    def subscribe(self, channel: str, callback):
        """订阅频道并处理消息"""
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe(**{channel: callback})
        
        logging.info(f"开始监听频道: {channel}")
        for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    callback(data)
                except Exception as e:
                    print(f"消息处理失败: {e}")
    
    def push_to_queue(self, queue_name: str, item: Dict[str, Any]):
        """推送到队列（用于任务队列）"""
        try:
            serialized_item = json.dumps(item, default=str)
            self.redis_client.lpush(queue_name, serialized_item)
        except Exception as e:
            print(f"队列推送失败: {e}")
    
    def pop_from_queue(self, queue_name: str, timeout: int = 0) -> Optional[Dict[str, Any]]:
        """从队列弹出项目（阻塞模式）"""
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
            print(f"队列弹出失败: {e}")
        return None
    
    def get_queue_length(self, queue_name: str) -> int:
        """获取队列长度"""
        return self.redis_client.llen(queue_name)

# 全局消息队列实例
mq = MessageQueue()
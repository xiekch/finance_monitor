from abc import ABC, abstractmethod
from typing import Dict, Any, List, Callable
import threading
from core.message_queue import mq
from core.message_types import BaseMessage, MessageType


class BaseConsumer(ABC):
    """消费者基类"""
    
    def __init__(self, consumer_name: str, message_types: List[MessageType]):
        self.consumer_name = consumer_name
        self.message_types = message_types
        self.is_running = False
        self.threads: List[threading.Thread] = []
        self.message_handlers: Dict[str, Callable] = {}
    
    @abstractmethod
    def process_message(self, message: BaseMessage):
        """处理消息（由子类实现）"""
        pass
    
    def _create_message_handler(self, message_type: MessageType) -> Callable:
        """为每种消息类型创建处理函数"""
        def handler(data):
            try:
                message = BaseMessage.from_dict(data)
                print(f"[{self.consumer_name}] 收到 {message_type.value} 消息: {message}")
                self.process_message(message)
            except Exception as e:
                print(f"[{self.consumer_name}] 处理 {message_type.value} 消息失败: {e}")
        return handler
    
    def _subscribe_channel(self, message_type: MessageType):
        """在独立线程中订阅一个频道"""
        channel = f"channel_{message_type.value}"
        handler = self._create_message_handler(message_type)
        
        print(f"[{self.consumer_name}] 开始订阅频道: {channel}")
        mq.subscribe(channel, handler)
    
    def start_consumption(self):
        """开始消费消息"""
        if self.is_running:
            print(f"[{self.consumer_name}] 消费者已在运行中")
            return
        
        self.is_running = True
        self.threads = []
        
        # 为每种消息类型创建一个专用线程
        for message_type in self.message_types:
            thread = threading.Thread(
                target=self._subscribe_channel,
                args=(message_type,),
                name=f"{self.consumer_name}_{message_type.value}"
            )
            thread.daemon = True
            thread.start()
            self.threads.append(thread)
        
        print(f"[{self.consumer_name}] 消费者已启动，监听: {[mt.value for mt in self.message_types]}")
        print(f"[{self.consumer_name}] 创建了 {len(self.threads)} 个订阅线程")
    
    def stop_consumption(self):
        """停止消费消息"""
        self.is_running = False
        
        # 取消订阅所有频道
        for message_type in self.message_types:
            channel = f"channel_{message_type.value}"
            mq.unsubscribe(channel)  # 假设 mq 有 unsubscribe 方法
        
        print(f"[{self.consumer_name}] 消费者已停止")
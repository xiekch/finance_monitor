from abc import ABC, abstractmethod
from typing import Dict, Any
from core.message_queue import mq
from core.message_types import BaseMessage, MessageType

class BaseConsumer(ABC):
    """消费者基类"""
    
    def __init__(self, consumer_name: str, message_types: list):
        self.consumer_name = consumer_name
        self.message_types = message_types
        self.is_running = False
    
    @abstractmethod
    def process_message(self, message: BaseMessage):
        """处理消息（由子类实现）"""
        pass
    
    def start_consumption(self):
        """开始消费消息"""
        import threading
        
        self.is_running = True
        
        def consumption_loop():
            while self.is_running:
                for message_type in self.message_types:
                    channel = f"channel_{message_type.value}"
                    
                    # 使用Redis的发布订阅模式
                    def message_handler(data):
                        try:
                            message = BaseMessage.from_dict(data)
                            self.process_message(message)
                        except Exception as e:
                            print(f"[{self.consumer_name}] 处理消息失败: {e}")
                    
                    # 在单独的线程中订阅每个频道
                    thread = threading.Thread(
                        target=mq.subscribe,
                        args=(channel, message_handler)
                    )
                    thread.daemon = True
                    thread.start()
                
                # 防止CPU占用过高
                import time
                time.sleep(1000)
        
        thread = threading.Thread(target=consumption_loop)
        thread.daemon = True
        thread.start()
        print(f"[{self.consumer_name}] 消费者已启动，监听: {[mt.value for mt in self.message_types]}")
    
    def stop_consumption(self):
        """停止消费消息"""
        self.is_running = False
        print(f"[{self.consumer_name}] 消费者已停止")
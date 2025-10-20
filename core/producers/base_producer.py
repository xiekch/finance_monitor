from abc import ABC, abstractmethod
from typing import List
from core.message_queue import mq
from core.message_types import BaseMessage

class BaseProducer(ABC):
    """生产者基类"""
    
    def __init__(self, producer_name: str):
        self.producer_name = producer_name
        self.is_running = False
    
    @abstractmethod
    async def produce_data(self) -> List[BaseMessage]:
        """生产数据（异步方法，由子类实现）"""
        pass
    
    def publish_message(self, message: BaseMessage, channel: str = None):
        """发布消息到消息队列"""
        if channel is None:
            channel = f"channel_{message.message_type.value}"
        
        mq.publish(channel, message.to_dict())
        print(f"[{self.producer_name}] 发布消息到 {channel}: {message.message_id}")
    
    def start_production(self, interval: int = 60):
        """开始生产数据"""
        import asyncio
        import threading
        
        self.is_running = True
        
        async def production_loop():
            while self.is_running:
                try:
                    messages = await self.produce_data()
                    for message in messages:
                        self.publish_message(message)
                    
                    print(f"[{self.producer_name}] 本轮生产完成，生成 {len(messages)} 条消息")
                    
                except Exception as e:
                    print(f"[{self.producer_name}] 生产数据失败: {e}")
                
                await asyncio.sleep(interval)
        
        def run_async_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(production_loop())
            finally:
                loop.close()
        
        thread = threading.Thread(target=run_async_loop)
        thread.daemon = True
        thread.start()
        print(f"[{self.producer_name}] 生产者已启动，间隔: {interval}秒")
    
    def stop_production(self):
        """停止生产数据"""
        self.is_running = False
        print(f"[{self.producer_name}] 生产者已停止")
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from core.message_queue import mq
from core.message_types import BaseMessage
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import asyncio
import threading
from datetime import datetime

class BaseProducer(ABC):
    """生产者基类 - 支持立即执行和忽略调度"""
    
    def __init__(self, producer_name: str, run_immediately: bool = False, ignore_schedule: bool = False):
        """
        初始化生产者
        
        Args:
            producer_name: 生产者名称
            run_immediately: 是否在启动时立即执行一次
            ignore_schedule: 是否忽略调度，只执行一次
        """
        self.producer_name = producer_name
        self.run_immediately = run_immediately
        self.ignore_schedule = ignore_schedule
        self.is_running = False
        self.scheduler = BackgroundScheduler()
        self._setup_scheduler_listeners()
    
    @abstractmethod
    async def produce_data(self) -> List[BaseMessage]:
        """生产数据（异步方法，由子类实现）"""
        pass
    
    @abstractmethod
    def create_trigger(self) -> BaseTrigger:
        """
        创建调度触发器（由子类实现）
        返回 APScheduler 的 BaseTrigger 对象
        """
        pass
    
    def publish_message(self, message: BaseMessage, channel: str = None):
        """发布消息到消息队列"""
        if channel is None:
            channel = f"channel_{message.message_type.value}"
        
        mq.publish(channel, message.to_dict())
        logging.info(f"[{self.producer_name}] 发布消息到 {channel}: {message.message_id}")
    
    def _setup_scheduler_listeners(self):
        """设置调度器事件监听器"""
        def job_success_listener(event):
            if event.job_id == f"{self.producer_name}_job":
                logging.info(f"[{self.producer_name}] 任务执行成功")
        
        def job_error_listener(event):
            if event.job_id == f"{self.producer_name}_job":
                logging.error(f"[{self.producer_name}] 任务执行失败: {event.exception}")
        
        self.scheduler.add_listener(job_success_listener, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(job_error_listener, EVENT_JOB_ERROR)
    
    def start_production(self):
        """开始生产数据"""
        try:
            # 如果设置了立即执行，先执行一次
            if self.run_immediately:
                logging.info(f"[{self.producer_name}] 立即执行生产任务")
                self._run_production_task()
            
            # 如果不忽略调度，设置定时任务
            if not self.ignore_schedule:
                trigger = self.create_trigger()
                
                # 添加作业
                self.scheduler.add_job(
                    self._run_production_task,
                    trigger=trigger,
                    id=f"{self.producer_name}_job",
                    name=f"{self.producer_name} Production Job",
                    max_instances=1,
                    replace_existing=True
                )
                
                # 启动调度器
                self.scheduler.start()
                logging.info(f"[{self.producer_name}] APScheduler 生产者已启动")
                logging.info(f"[{self.producer_name}] 使用触发器: {type(trigger).__name__}")
            else:
                logging.info(f"[{self.producer_name}] 忽略调度设置，仅执行一次")
            
            self.is_running = True
            
        except Exception as e:
            logging.error(f"[{self.producer_name}] 启动调度器失败: {e}")
            raise
    
    def _run_production_task(self):
        """运行生产任务的同步包装器"""
        def run_async_task():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._production_wrapper())
            except Exception as e:
                logging.error(f"[{self.producer_name}] 异步任务执行失败: {e}")
            finally:
                loop.close()
        
        thread = threading.Thread(target=run_async_task)
        thread.daemon = True
        thread.start()
    
    async def _production_wrapper(self):
        """生产任务包装器"""
        try:
            start_time = datetime.now()
            logging.info(f"[{self.producer_name}] 开始执行生产任务")
            
            messages = await self.produce_data()
            
            for message in messages:
                self.publish_message(message)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            logging.info(f"[{self.producer_name}] 生产任务完成，生成 {len(messages)} 条消息，耗时 {duration:.2f} 秒")
            
            # 如果忽略调度，执行一次后停止
            if self.ignore_schedule and not self.run_immediately:
                self.stop_production()
            
        except Exception as e:
            logging.error(f"[{self.producer_name}] 生产任务执行失败: {e}")
    
    def stop_production(self):
        """停止生产数据"""
        if hasattr(self, 'scheduler') and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        
        self.is_running = False
        logging.info(f"[{self.producer_name}] 生产者已停止")
    
    def get_next_run_time(self):
        """获取下一次运行时间"""
        if self.ignore_schedule:
            return "忽略调度，仅执行一次"
        
        job = self.scheduler.get_job(f"{self.producer_name}_job")
        return job.next_run_time if job else None
    
    def pause_production(self):
        """暂停生产"""
        if not self.ignore_schedule:
            self.scheduler.pause_job(f"{self.producer_name}_job")
            logging.info(f"[{self.producer_name}] 生产者已暂停")
        else:
            logging.info(f"[{self.producer_name}] 忽略调度的生产者无法暂停")
    
    def resume_production(self):
        """恢复生产"""
        if not self.ignore_schedule:
            self.scheduler.resume_job(f"{self.producer_name}_job")
            logging.info(f"[{self.producer_name}] 生产者已恢复")
        else:
            logging.info(f"[{self.producer_name}] 忽略调度的生产者无法恢复")
    
    def run_once(self):
        """手动执行一次生产任务"""
        logging.info(f"[{self.producer_name}] 手动触发生产任务")
        self._run_production_task()
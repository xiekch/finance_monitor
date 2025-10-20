from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

class MessageType(Enum):
    """消息类型枚举"""
    PRICE_DATA = "price_data"           # 价格数据
    VOLATILITY_ALERT = "volatility_alert" # 波动告警
    TASK_REQUEST = "task_request"       # 任务请求
    TASK_RESULT = "task_result"         # 任务结果
    SYSTEM_EVENT = "system_event"       # 系统事件

class FrequencyType(Enum):
    """频率类型枚举"""
    MINUTE = "minute"
    DAILY = "daily" 
    WEEKLY = "weekly"

@dataclass
class BaseMessage:
    """基础消息类"""
    message_id: str
    message_type: MessageType
    timestamp: datetime
    source: str
    payload: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result['message_type'] = self.message_type.value
        result['timestamp'] = self.timestamp.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """从字典创建"""
        data['message_type'] = MessageType(data['message_type'])
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)

@dataclass
class PriceDataMessage(BaseMessage):
    """价格数据消息"""
    symbol: str
    market: str
    frequency: FrequencyType
    
    def __init__(self, symbol: str, market: str, frequency: FrequencyType, 
                 price_data: Dict[str, Any], source: str):
        super().__init__(
            message_id=f"price_{symbol}_{market}_{frequency.value}_{datetime.now().timestamp()}",
            message_type=MessageType.PRICE_DATA,
            timestamp=datetime.now(),
            source=source,
            payload=price_data
        )
        self.symbol = symbol
        self.market = market
        self.frequency = frequency

@dataclass
class VolatilityAlertMessage(BaseMessage):
    """波动告警消息"""
    def __init__(self, alert_data: Dict[str, Any], source: str):
        super().__init__(
            message_id=f"alert_{datetime.now().timestamp()}",
            message_type=MessageType.VOLATILITY_ALERT,
            timestamp=datetime.now(),
            source=source,
            payload=alert_data
        )

@dataclass
class TaskRequestMessage(BaseMessage):
    """任务请求消息"""
    def __init__(self, task_type: str, task_data: Dict[str, Any], source: str):
        super().__init__(
            message_id=f"task_{task_type}_{datetime.now().timestamp()}",
            message_type=MessageType.TASK_REQUEST,
            timestamp=datetime.now(),
            source=source,
            payload={'task_type': task_type, 'task_data': task_data}
        )

@dataclass
class SystemEventMessage(BaseMessage):
    """系统事件消息"""
    def __init__(self, event_type: str, event_data: Dict[str, Any], source: str):
        super().__init__(
            message_id=f"event_{event_type}_{datetime.now().timestamp()}",
            message_type=MessageType.SYSTEM_EVENT,
            timestamp=datetime.now(),
            source=source,
            payload={'event_type': event_type, 'event_data': event_data}
        )
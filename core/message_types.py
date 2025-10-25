from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

import uuid


class MessageType(Enum):
    """消息类型枚举"""

    PRICE_DATA = "price_data"  # 价格数据
    HISTORICAL_PRICE_DATA = "historical_price_data"  # 历史价格数据
    VOLATILITY_ALERT = "volatility_alert"  # 波动告警
    TASK_REQUEST = "task_request"  # 任务请求
    TASK_RESULT = "task_result"  # 任务结果
    SYSTEM_EVENT = "system_event"  # 系统事件


class FrequencyType(Enum):
    MINUTE = "1m"
    DAILY = "1d"
    WEEKLY = "1w"


@dataclass
class BaseMessage:
    """基础消息类"""

    message_id: str
    message_type: MessageType
    timestamp: datetime
    source: str
    payload: Dict[str, Any]

    def __init__(
        self,
        message_type: MessageType,
        source: str,
        payload: Dict[str, Any] = None,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
    ):
        self.message_id = message_id or str(uuid.uuid4())
        self.message_type = message_type
        self.timestamp = timestamp or datetime.now()
        self.source = source
        self.payload = payload or {}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["message_type"] = self.message_type.value
        result["timestamp"] = self.timestamp.isoformat()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """从字典创建"""
        data["message_type"] = MessageType(data["message_type"])
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


@dataclass
class PriceDataMessage(BaseMessage):
    """价格数据消息"""

    def __init__(
        self,
        payload: Dict[str, Any],
        source: str,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
        message_type: MessageType = MessageType.PRICE_DATA,
    ):
        super().__init__(
            message_type=message_type,
            timestamp=timestamp,
            source=source,
            payload=payload,
            message_id=message_id,
        )


@dataclass
class VolatilityAlertMessage(BaseMessage):
    """波动告警消息"""

    def __init__(
        self,
        payload: Dict[str, Any],
        source: str,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
        message_type=MessageType.VOLATILITY_ALERT,
    ):
        super().__init__(
            message_type=message_type,
            timestamp=timestamp,
            source=source,
            payload=payload,
            message_id=message_id,
        )


@dataclass
class TaskRequestMessage(BaseMessage):
    """任务请求消息"""

    task_type: str

    def __init__(
        self,
        task_type: str,
        task_data: Dict[str, Any],
        source: str,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
        message_type=MessageType.TASK_REQUEST,
    ):
        payload = {"task_type": task_type, "task_data": task_data}

        super().__init__(
            message_type=message_type,
            timestamp=timestamp,
            source=source,
            payload=payload,
            message_id=message_id,
        )
        self.task_type = task_type


@dataclass
class SystemEventMessage(BaseMessage):
    """系统事件消息"""

    def __init__(
        self,
        payload: Dict[str, Any],
        source: str,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
        message_type=MessageType.SYSTEM_EVENT
    ):

        super().__init__(
            message_type=message_type,
            timestamp=timestamp,
            source=source,
            payload=payload,
            message_id=message_id,
        )

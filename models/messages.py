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
    SOCIAL_POST_BATCH = "social_post_batch"   # 一批新拉到的推文
    AI_BRIEFING = "ai_briefing"               # LLM 已生成的简报


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
        """从字典创建。不修改入参（memory backend 会跨消费者共享同一 dict）。"""
        data = dict(data)
        data["message_type"] = MessageType(data["message_type"])
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "BaseMessage":
        """根据 data['message_type'] 查 MESSAGE_CLASSES 还原成对应子类。

        Redis backend 收到 json 反序列化出来的 dict 时调用；新增 MessageType
        时记得在文件底部 MESSAGE_CLASSES 注册。
        """
        mt = MessageType(data["message_type"])
        try:
            cls = MESSAGE_CLASSES[mt]
        except KeyError as e:
            raise ValueError(
                f"未注册的 MessageType: {mt}; 在 MESSAGE_CLASSES 里登记一下"
            ) from e
        return cls.from_dict(data)


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


@dataclass
class SocialPostBatchMessage(BaseMessage):
    """一批新拉到的推文，作为 LLM 输入的原料。"""
    def __init__(
        self,
        payload: Dict[str, Any],
        source: str,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
        message_type: MessageType = MessageType.SOCIAL_POST_BATCH,
    ):
        super().__init__(
            message_type=message_type,
            timestamp=timestamp,
            source=source,
            payload=payload,
            message_id=message_id,
        )


@dataclass
class AIBriefingMessage(BaseMessage):
    """LLM 已生成的简报。"""
    def __init__(
        self,
        payload: Dict[str, Any],
        source: str,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
        message_type: MessageType = MessageType.AI_BRIEFING,
    ):
        super().__init__(
            message_type=message_type,
            timestamp=timestamp,
            source=source,
            payload=payload,
            message_id=message_id,
        )


# MessageType → 对应 BaseMessage 子类的注册表，给 Redis backend
# 反序列化时按 type 路由用。新增 MessageType 时记得在这里加一条。
# - PRICE_DATA 与 HISTORICAL_PRICE_DATA 共用 PriceDataMessage
# - TASK_REQUEST / TASK_RESULT 当前代码无 publish 路径，未注册；
#   要启用时需保证子类 __init__ 能接受 from_dict 反序列出的字段。
MESSAGE_CLASSES: Dict[MessageType, type] = {
    MessageType.PRICE_DATA: PriceDataMessage,
    MessageType.HISTORICAL_PRICE_DATA: PriceDataMessage,
    MessageType.VOLATILITY_ALERT: VolatilityAlertMessage,
    MessageType.SYSTEM_EVENT: SystemEventMessage,
    MessageType.SOCIAL_POST_BATCH: SocialPostBatchMessage,
    MessageType.AI_BRIEFING: AIBriefingMessage,
}

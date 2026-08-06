"""SSE 帧封装：POST 流式接口使用，事件协议见 README"""
import json
from typing import Any


def sse_format(event: str, data: dict[str, Any]) -> str:
    """构造一个 SSE 命名事件帧：
    event: <事件名>
    data: <JSON>
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_ping() -> str:
    """心跳帧，防止代理断连"""
    return ": ping\n\n"

"""业务异常：统一错误码，HTTP 层转换为 4xx/5xx"""


class BizError(Exception):
    """业务错误：code 用于 SSE error 事件 / HTTP 响应，message 为用户可读信息"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

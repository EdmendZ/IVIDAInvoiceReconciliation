"""把第三方异常转换为可公开的稳定错误契约。"""


class ExternalServiceError(RuntimeError):
    """外部供应商错误的安全、稳定、可重试表示。

    code 供状态机和排障使用；safe_message 可返回 UI；原异常只保留在异常链与
    服务端日志中，避免泄露 Token、URL 或供应商响应。
    """

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable

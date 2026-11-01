"""业务错误：CLI、API、MCP 共用的退出码与错误类型。"""


class PanwebError(Exception):
    def __init__(self, exit_code, err_type, message, hint=None):
        super().__init__(message)
        self.exit_code = exit_code
        self.err_type = err_type
        self.message = message
        self.hint = hint

    def to_dict(self):
        return {"ok": False, "error": {"type": self.err_type,
                                       "message": self.message,
                                       "exit_code": self.exit_code,
                                       "hint": self.hint}}


class TunnelError(Exception):
    pass

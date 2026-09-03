"""日志服务。

Cordis 里 ``ctx.logger`` 是每个插件独享的、带名字前缀的日志记录器。这里保留
同名语义，但落到 Python 标准库 :mod:`logging` 上，并且允许宿主应用替换
:meth:`LoggerService.handler` 来把日志接到界面上。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

_LOGGER_NAME = "cordis"


class Logger:
    """带名字前缀的记录器。"""

    LEVELS = ("debug", "info", "warn", "error")

    def __init__(self, name: str = "", handler: Callable[[str, str, Any], None] | None = None) -> None:
        self.name = name
        self._handler = handler
        self._logging = logging.getLogger(_LOGGER_NAME)

    # ------------------------------------------------------------------ 输出
    def _emit(self, level: str, *args: Any) -> None:
        message = " ".join(str(arg) for arg in args)
        if self._handler is not None:
            self._handler(level, message, self.name)
            return
        record = f"[{self.name}] {message}" if self.name else message
        # 注意：logging.warn 在 Python 3.14 已弃用，这里统一用 warning
        getattr(self._logging, "warning" if level == "warn" else level)(record)

    def debug(self, *args: Any) -> None:
        self._emit("debug", *args)

    def info(self, *args: Any) -> None:
        self._emit("info", *args)

    def warn(self, *args: Any) -> None:
        self._emit("warn", *args)

    def error(self, *args: Any) -> None:
        self._emit("error", *args)

    def extend(self, name: str) -> "Logger":
        """派生一个子记录器。"""
        child = Logger(f"{self.name}:{name}" if self.name else name, self._handler)
        return child


class LoggerService(Logger):
    """``ctx.logger`` —— 插件日志的入口。"""

    def __init__(self, ctx: "Any") -> None:
        super().__init__("")
        self.ctx = ctx

    def extend(self, name: str) -> Logger:
        return Logger(name, self._handler)

    def set_handler(self, handler: Callable[[str, str, Any], None] | None) -> None:
        """替换全局日志出口（例如把日志转发到状态栏）。"""
        self._handler = handler


__all__ = ["Logger", "LoggerService"]

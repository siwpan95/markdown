"""TkinterWeb 后端插件。

注册优先级最高：它支持完整 CSS 2.1，表格、引用、提示块的表现最好。
缺点是依赖 Tkhtml 的预编译二进制，只提供到 Tcl/Tk 8.6 —— 在 Tcl/Tk 9
（Python 3.13+ 常见）下构造会抛 ``OSError``，此时 :class:`BackendService`
会自动降级到下一个后端。
"""

from __future__ import annotations

from typing import Any


def apply(ctx: Any, config: Any = None) -> None:
    from .. import events
    from ..backends import SHORT_LABELS
    from ..backends.tkinterweb_backend import TkinterWebBackend

    def factory(_ctx: Any, theme: Any, font_size: int) -> Any:
        return TkinterWebBackend(
            ctx.window.content,
            theme,
            font_size,
            on_link=lambda target: ctx.emit(events.LINK_OPEN, target),
        )

    ctx.backends.register(
        TkinterWebBackend.key,
        TkinterWebBackend.label,
        factory,
        priority=10,
        supports_css=TkinterWebBackend.supports_css,
        menu_label=SHORT_LABELS[TkinterWebBackend.key],
    )


apply.name = "backend/tkinterweb"
apply.inject = ["backends", "window"]

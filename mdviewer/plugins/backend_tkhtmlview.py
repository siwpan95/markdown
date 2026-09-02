"""tkhtmlview 后端插件。

兼容性最好的默认选择：纯 Python 实现，只用标准库的 ``html.parser`` 把 HTML
翻译成 ``Text`` 的 tag，因此不挑 Tcl/Tk 版本。代价是只认六个内联样式属性，
``<style>`` 样式表会被当成正文显示——渲染器为此专门准备了 ``simple`` 档位。
"""

from __future__ import annotations

from typing import Any


def apply(ctx: Any, config: Any = None) -> None:
    from .. import events
    from ..backends import SHORT_LABELS
    from ..backends.tkhtmlview_backend import TkhtmlviewBackend

    def factory(_ctx: Any, theme: Any, font_size: int) -> Any:
        return TkhtmlviewBackend(
            ctx.window.content,
            theme,
            font_size,
            on_link=lambda target: ctx.emit(events.LINK_OPEN, target),
        )

    ctx.backends.register(
        TkhtmlviewBackend.key,
        TkhtmlviewBackend.label,
        factory,
        priority=20,
        supports_css=TkhtmlviewBackend.supports_css,
        menu_label=SHORT_LABELS[TkhtmlviewBackend.key],
    )


apply.name = "backend/tkhtmlview"
apply.inject = ["backends", "window"]

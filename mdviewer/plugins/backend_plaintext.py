"""纯文本后端插件。

兜底方案：直接展示 Markdown 源码，不依赖任何第三方包。目录标题从源码里用
正则提取，因此即使它上面两个后端都不可用，目录侧栏依然能工作。
"""

from __future__ import annotations

from typing import Any


def apply(ctx: Any, config: Any = None) -> None:
    from .. import events
    from ..backends import SHORT_LABELS
    from ..backends.plaintext_backend import PlainTextBackend

    def factory(_ctx: Any, theme: Any, font_size: int) -> Any:
        return PlainTextBackend(
            ctx.window.content,
            theme,
            font_size,
            on_link=lambda target: ctx.emit(events.LINK_OPEN, target),
        )

    ctx.backends.register(
        PlainTextBackend.key,
        PlainTextBackend.label,
        factory,
        priority=90,
        supports_css=PlainTextBackend.supports_css,
        menu_label=SHORT_LABELS[PlainTextBackend.key],
    )


apply.name = "backend/plaintext"
apply.inject = ["backends", "window"]

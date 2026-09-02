"""状态栏插件。

左侧显示文档信息（路径 / 编码 / 统计），右侧显示当前渲染后端与降级原因。
两者的数据来源完全不同，但都只是“监听事件 → 更新文本”，因此这个插件里
没有任何业务判断。
"""

from __future__ import annotations

from typing import Any

from .. import events


def apply(ctx: Any, config: Any = None) -> None:
    from ..widgets.status_bar import StatusBar

    bar = StatusBar(ctx.window.bottom)
    bar.pack(side="bottom", fill="x")

    def on_rendered(_result: Any) -> None:
        document = ctx.documents.current
        if document is None:
            bar.set_left("就绪")
            return
        bar.set_left(
            f"{document.path}  ·  {document.encoding}  ·  {document.stats.as_text()}"
        )

    def on_backend_change(_backend: Any) -> None:
        bar.set_right(ctx.backends.status_text)

    def on_message(text: str) -> None:
        bar.set_left(text)

    ctx.on(events.DOC_RENDERED, on_rendered)
    ctx.on(events.DOC_ERROR, lambda path, message: on_message(str(message)))
    ctx.on(events.BACKEND_CHANGE, on_backend_change)
    ctx.on(events.STATUS_MESSAGE, on_message)


apply.name = "status"
apply.inject = ["documents", "backends", "window"]

"""页内查找插件。

查找条本身只负责输入与导航交互，真正的匹配/高亮由当前后端提供
（``backend.find`` / ``find_next`` / ``find_prev`` / ``clear_find``）。
后端不支持查找时（例如纯文本后端的部分情况）这些方法返回 0，界面显示
“无匹配”，不需要插件做能力判断。
"""

from __future__ import annotations

from typing import Any

from .. import events


def apply(ctx: Any, config: Any = None) -> None:
    from ..widgets.find_bar import FindBar

    def backend():
        return ctx.backends.current

    def run_query(query: str, nocase: bool) -> int:
        current = backend()
        return current.find(query, nocase=nocase) if current else 0

    def find_next() -> int:
        current = backend()
        return current.find_next() if current else 0

    def find_prev() -> int:
        current = backend()
        return current.find_prev() if current else 0

    def clear() -> None:
        current = backend()
        if current:
            current.clear_find()

    bar = FindBar(
        ctx.window.bottom,
        on_query=run_query,
        on_next=find_next,
        on_prev=find_prev,
        on_close=clear,
    )

    def show() -> None:
        # 挂在窗口底部区域的顶部，因此始终显示在状态栏上方
        bar.pack(side="top", fill="x")
        bar.focus_entry()

    def hide() -> None:
        bar.close()

    ctx.on(events.ACTION_SHOW_FIND, show)
    ctx.on(events.ACTION_HIDE_FIND, hide)


apply.name = "find"
apply.inject = ["backends", "window"]

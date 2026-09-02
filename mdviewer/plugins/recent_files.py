"""最近打开文件插件。

菜单项由本插件填充，而不是由 ``shell`` 代劳：``shell`` 只负责建出「最近打开」
这个子菜单，然后在 :data:`~mdviewer.events.MENU_FILE` 事件里把它广播出来。

这样加一个“固定到列表”“按目录分组”之类的功能，都不需要去改 shell。
列表内容变化时（打开新文件、清空列表、文件被删除）自动重建。
"""

from __future__ import annotations

from tkinter import messagebox
from typing import Any

from .. import events
from ..core.config import APP_NAME


def apply(ctx: Any, config: Any = None) -> None:
    menu = None

    def rebuild() -> None:
        # shell 卸载后菜单会一并销毁，这里做存在性检查避免 TclError
        if menu is None or not menu.winfo_exists():
            return
        menu.delete(0, "end")
        files = ctx.documents.recent_files()
        if not files:
            menu.add_command(label="（无）", state="disabled")
            return
        for path in files:
            menu.add_command(label=path, command=lambda p=path: ctx.documents.open(p))
        menu.add_separator()
        menu.add_command(
            label="清空列表",
            command=lambda: (
                ctx.documents.clear_recent(),
                ctx.emit(events.STATUS_MESSAGE, "已清空最近打开列表"),
            ),
        )

    def on_menu_file(file_menu: Any) -> None:
        nonlocal menu
        menu = ctx.window.submenu("文件", "最近打开")
        rebuild()

    def on_settings_change(key: str, value: Any) -> None:
        if key == "recent_files":
            rebuild()

    def on_error(path: Any, message: str) -> None:
        # 文件已被删除时，提示一次即可；列表由 settings 的变化驱动重建
        try:
            messagebox.showerror(APP_NAME, message)
        except Exception:  # noqa: BLE001 - 无界面环境下忽略
            pass

    ctx.on(events.MENU_FILE, on_menu_file)
    ctx.on(events.SETTINGS_CHANGE, on_settings_change)
    ctx.on(events.DOC_ERROR, on_error)


apply.name = "recent-files"
apply.inject = ["documents", "window"]

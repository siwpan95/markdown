"""外观插件。

负责把「主题 / 字号 / 后端」这些服务里的**数据**变成界面上的**样式**：

* 换肤时同步 ttk 控件配色 —— 默认的 ``vista`` / ``x11`` 主题会忽略大部分背景
  设置，深色模式下必须切到 ``clam``（唯一能被完整自定义配色的内置 ttk 主题）；
* 响应 :data:`~mdviewer.events.ACTION_TOGGLE_THEME` /
  :data:`~mdviewer.events.ACTION_ZOOM` / ``ACTION_SWITCH_BACKEND`` 三个用户动作。

服务不知道 Tk 的存在，插件不知道配色怎么算——两边只通过事件耦合。
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from typing import Any

from .. import events


def apply(ctx: Any, config: Any = None) -> None:
    def apply_window_theme(theme: Any) -> None:
        root = ctx.window.root
        try:
            root.configure(background=theme.body_bg)
        except tk.TclError:
            pass

        dark = theme.key == "dark"
        style = ttk.Style()
        if dark:
            try:
                style.theme_use("clam")
            except tk.TclError:
                return
            background = theme.body_bg
            panel = "#2b303b"
            foreground = theme.body_fg
            style.configure(
                ".", background=background, foreground=foreground, fieldbackground=panel
            )
            for name in (
                "TFrame",
                "TLabel",
                "TPanedwindow",
                "TLabelframe",
                "TLabelframe.Label",
                "TCheckbutton",
                "TRadiobutton",
            ):
                style.configure(name, background=background, foreground=foreground)
            style.configure(
                "TButton", background=panel, foreground=foreground, borderwidth=1
            )
            style.map("TButton", background=[("active", "#3b4048")])
            style.configure(
                "TEntry",
                fieldbackground=panel,
                foreground=foreground,
                insertcolor=foreground,
            )
            style.configure(
                "Treeview",
                background=background,
                foreground=foreground,
                fieldbackground=background,
            )
            style.map("Treeview", background=[("selected", "#3b4048")])
            style.configure("Vertical.TScrollbar", background=panel)
            style.configure("Horizontal.TScrollbar", background=panel)
        else:
            try:
                style.theme_use(
                    "vista" if sys.platform.startswith("win") else "default"
                )
                style.configure(".", background="", foreground="")
            except tk.TclError:
                pass

    def on_toggle_theme() -> None:
        ctx.themes.toggle()

    def on_zoom(delta: int) -> None:
        ctx.themes.zoom(delta)

    def on_switch_backend(key: str) -> None:
        try:
            ctx.backends.switch(key)
        except Exception as error:  # noqa: BLE001 - 切换失败时保持原后端
            ctx.emit(events.STATUS_MESSAGE, f"切换后端失败：{error}")

    ctx.on(events.APP_READY, lambda _file: apply_window_theme(ctx.themes.current))
    ctx.on(events.THEME_CHANGE, apply_window_theme)
    ctx.on(events.ACTION_TOGGLE_THEME, on_toggle_theme)
    ctx.on(events.ACTION_ZOOM, on_zoom)
    ctx.on(events.ACTION_SWITCH_BACKEND, on_switch_backend)


apply.name = "appearance"
apply.inject = ["themes", "backends", "window"]

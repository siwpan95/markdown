"""外壳插件：菜单、工具栏、快捷键、文件对话框。

这是**最后一个**被加载的插件，原因有两个：

1. 它要按固定顺序往菜单里塞条目，放在最后能保证「最近打开」这类由别的插件
   填充的子菜单已经建好；
2. 它建的菜单会通过 :data:`~mdviewer.events.MENU_FILE` 等事件广播出去，
   最后加载才能保证其他插件的监听器已经注册。

本插件只做**触发**：每个菜单项/按钮/快捷键都只是发出一个 ``action/*`` 事件，
具体行为由 ``viewer`` / ``exporter`` / ``appearance`` / ``toc`` 实现。唯一的
例外是文件选择对话框和「关于」——它们本身就是纯 UI，没有拆分的必要。
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

from .. import events
from ..core.config import APP_NAME, VERSION

#: (显示文本, 事件名, 提示) —— 工具栏按钮与快捷键共用同一份定义
TOOLBAR_BUTTONS = (
    ("打开", events.ACTION_OPEN_FILE, "打开 Markdown 文件 (Ctrl+O)"),
    ("重新加载", events.ACTION_RELOAD, "重新读取当前文件 (F5)"),
    ("目录", events.ACTION_TOGGLE_TOC, "显示/隐藏目录 (Ctrl+T)"),
    ("主题", events.ACTION_TOGGLE_THEME, "切换浅色/深色 (Ctrl+D)"),
    ("A-", events.ACTION_ZOOM, "缩小字号 (Ctrl+-)"),
    ("A+", events.ACTION_ZOOM, "放大字号 (Ctrl+=)"),
    ("查找", events.ACTION_SHOW_FIND, "页内查找 (Ctrl+F)"),
    ("导出 HTML", events.ACTION_EXPORT_HTML, "导出为独立 HTML (Ctrl+E)"),
    ("浏览器打开", events.ACTION_OPEN_BROWSER, "用默认浏览器打开 (Ctrl+B)"),
)

#: (按键序列, 事件名, 传给事件的参数)
SHORTCUTS = (
    ("<Control-o>", events.ACTION_OPEN_FILE, None),
    ("<Control-O>", events.ACTION_OPEN_FILE, None),
    ("<Control-f>", events.ACTION_SHOW_FIND, None),
    ("<Control-F>", events.ACTION_SHOW_FIND, None),
    ("<Control-e>", events.ACTION_EXPORT_HTML, None),
    ("<Control-b>", events.ACTION_OPEN_BROWSER, None),
    ("<Control-d>", events.ACTION_TOGGLE_THEME, None),
    ("<Control-t>", events.ACTION_TOGGLE_TOC, None),
    ("<Control-q>", events.ACTION_QUIT, None),
    ("<Control-equal>", events.ACTION_ZOOM, 1),
    ("<Control-plus>", events.ACTION_ZOOM, 1),
    ("<Control-minus>", events.ACTION_ZOOM, -1),
    ("<Control-0>", events.ACTION_ZOOM, 0),
    ("<F5>", events.ACTION_RELOAD, None),
    ("<Escape>", events.ACTION_HIDE_FIND, None),
)


def apply(ctx: Any, config: Any = None) -> None:
    import tkinter as tk

    window = ctx.window
    settings = ctx.settings

    # 菜单树由本插件创建，也由本插件拆除
    ctx.effect(window.drop_menus, "shell:menus")

    # ---------------------------------------------------------------- 文件菜单
    file_menu = window.menu("文件")
    file_menu.add_command(
        label="打开…",
        command=lambda: ctx.emit(events.ACTION_OPEN_FILE),
        accelerator="Ctrl+O",
    )
    file_menu.add_command(
        label="重新加载",
        command=lambda: ctx.emit(events.ACTION_RELOAD),
        accelerator="F5",
    )
    # 只建壳，条目由 recent-files 插件填充
    window.submenu("文件", "最近打开")
    file_menu.add_separator()
    file_menu.add_command(
        label="导出为 HTML…",
        command=lambda: ctx.emit(events.ACTION_EXPORT_HTML),
        accelerator="Ctrl+E",
    )
    file_menu.add_command(
        label="在浏览器中打开",
        command=lambda: ctx.emit(events.ACTION_OPEN_BROWSER),
        accelerator="Ctrl+B",
    )
    file_menu.add_separator()
    file_menu.add_command(
        label="退出", command=lambda: ctx.emit(events.ACTION_QUIT), accelerator="Ctrl+Q"
    )
    ctx.emit(events.MENU_FILE, file_menu)

    # ---------------------------------------------------------------- 视图菜单
    view_menu = window.menu("视图")

    toc_var = tk.BooleanVar(value=bool(settings.get("show_toc", True)))
    view_menu.add_checkbutton(
        label="显示目录",
        command=lambda: ctx.emit(events.ACTION_TOGGLE_TOC),
        variable=toc_var,
    )
    view_menu.add_command(
        label="切换主题",
        command=lambda: ctx.emit(events.ACTION_TOGGLE_THEME),
        accelerator="Ctrl+D",
    )

    auto_reload_var = tk.BooleanVar(value=bool(settings.get("auto_reload", True)))
    view_menu.add_checkbutton(
        label="文件变化时自动重载",
        command=lambda: settings.update(auto_reload=auto_reload_var.get()),
        variable=auto_reload_var,
    )
    wrap_var = tk.BooleanVar(value=bool(settings.get("word_wrap", True)))
    view_menu.add_checkbutton(
        label="自动换行",
        command=lambda: settings.update(word_wrap=wrap_var.get()),
        variable=wrap_var,
    )
    view_menu.add_separator()
    view_menu.add_command(
        label="放大字号",
        command=lambda: ctx.emit(events.ACTION_ZOOM, 1),
        accelerator="Ctrl+=",
    )
    view_menu.add_command(
        label="缩小字号",
        command=lambda: ctx.emit(events.ACTION_ZOOM, -1),
        accelerator="Ctrl+-",
    )
    view_menu.add_command(
        label="重置字号",
        command=lambda: ctx.emit(events.ACTION_ZOOM, 0),
        accelerator="Ctrl+0",
    )

    backend_var = tk.StringVar(value=str(settings.get("backend", "auto")))
    backend_menu = window.submenu("视图", "渲染后端")
    for key in ctx.backends.choices():
        backend_menu.add_radiobutton(
            label=ctx.backends.label(key),
            value=key,
            variable=backend_var,
            command=lambda k=key: ctx.emit(events.ACTION_SWITCH_BACKEND, k),
        )
    ctx.emit(events.MENU_VIEW, view_menu)

    # ---------------------------------------------------------------- 帮助菜单
    help_menu = window.menu("帮助")
    help_menu.add_command(
        label="关于", command=lambda: ctx.emit(events.ACTION_ABOUT)
    )
    ctx.emit(events.MENU_HELP, help_menu)

    # ---------------------------------------------------------------- 工具栏
    for text, event, tip in TOOLBAR_BUTTONS:
        if event is events.ACTION_ZOOM:
            delta = -1 if text == "A-" else 1
            command = lambda d=delta: ctx.emit(events.ACTION_ZOOM, d)
        else:
            command = lambda e=event: ctx.emit(e)
        # add_toolbar_button 返回撤销函数，交给 Fiber 托管
        ctx.effect(
            lambda t=text, c=command, p=tip: window.add_toolbar_button(t, c, p),
            f"toolbar:{text}",
        )

    # ---------------------------------------------------------------- 快捷键
    def bind_shortcut(sequence: str, event: str, argument: Any) -> None:
        def handler(_event: Any) -> None:
            if argument is None:
                ctx.emit(event)
            else:
                ctx.emit(event, argument)

        # window.bind 返回的撤销函数交给 Fiber 托管
        ctx.effect(lambda s=sequence, h=handler: window.bind(s, h))

    for sequence, event, argument in SHORTCUTS:
        bind_shortcut(sequence, event, argument)

    # ---------------------------------------------------------------- 行为
    def on_open_file() -> None:
        document = ctx.documents.current
        initial = str(document.directory) if document else str(Path.home())
        path = filedialog.askopenfilename(
            title="选择 Markdown 文件",
            initialdir=initial,
            filetypes=ctx.documents.file_types,
        )
        if path:
            ctx.documents.open(path)

    def on_quit() -> None:
        window.request_close()

    def on_about() -> None:
        from ..core.theme import THEMES

        messagebox.showinfo(
            APP_NAME,
            f"{APP_NAME} v{VERSION}\n\n"
            "一个基于 Cordis 插件架构的 Tkinter Markdown 查看器。\n"
            f"当前渲染后端：{ctx.backends.status_text}\n"
            f"可用主题：{', '.join(t.label for t in THEMES.values())}\n"
            f"已加载插件：{ctx.registry.size}",
        )

    def on_settings_change(key: str, value: Any) -> None:
        if key == "show_toc":
            toc_var.set(bool(value))
        elif key == "auto_reload":
            auto_reload_var.set(bool(value))
        elif key == "word_wrap":
            wrap_var.set(bool(value))
        elif key == "backend":
            backend_var.set(str(value))

    ctx.on(events.ACTION_OPEN_FILE, on_open_file)
    ctx.on(events.ACTION_RELOAD, lambda: ctx.documents.reload())
    ctx.on(events.ACTION_QUIT, on_quit)
    ctx.on(events.ACTION_ABOUT, on_about)
    ctx.on(events.SETTINGS_CHANGE, on_settings_change)


apply.name = "shell"
apply.inject = ["settings", "documents", "themes", "backends", "window"]

"""窗口服务 —— ``ctx.window``。

把 Tk 窗口的**骨架**与**内容**分开：本服务只提供区域（工具栏 / 主体 / 底部）、
菜单容器、以及一批会被自动清理的资源申请接口；具体的按钮、菜单项、面板都由
插件往里填。

所有申请型方法（``bind`` / ``after`` / ``add_pane`` / ``add_toolbar_button``）
都会在插件卸载时自动撤销，这是 Cordis “时间可组合性”的直接体现——插件消失后
不会残留监听器、定时器或孤儿控件。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Any, Callable

from cordis import Service

from .. import events
from ..core.config import APP_NAME

if TYPE_CHECKING:  # pragma: no cover
    from cordis import Context


class WindowService(Service):
    """主窗口的骨架与资源申请入口。"""

    name = "window"
    inject = ["settings"]

    def __init__(self, ctx: "Context", config: Any = None) -> None:
        super().__init__(ctx, config)
        options = self.config if isinstance(self.config, dict) else {}
        self.root: tk.Tk = options["root"]

        self._panes: dict[str, tuple[Any, int]] = {}
        self._visible: set[str] = set()
        self._after_ids: set[str] = set()
        self._menus: dict[str, tk.Menu] = {}
        self._menu_order: list[str] = []

        self.root.title(APP_NAME)
        self.root.geometry(self.ctx.settings.get("window_geometry", "1100x720"))
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)

        #: 工具栏
        self.toolbar = ttk.Frame(self.root, padding=(6, 4))
        self.toolbar.pack(side="top", fill="x")

        #: 主体：目录面板与正文左右分栏
        self.body = ttk.PanedWindow(self.root, orient="horizontal")
        self.body.pack(side="top", fill="both", expand=True)

        self.content = ttk.Frame(self.body)
        self.body.add(self.content, weight=1)

        #: 底部：查找栏（上）与状态栏（下）
        self.bottom = ttk.Frame(self.root)
        self.bottom.pack(side="bottom", fill="x")

    # ------------------------------------------------------------------ 菜单
    @property
    def menubar(self) -> tk.Menu:
        menu = self._menus.get("")
        if menu is None:
            menu = tk.Menu(self.root)
            self.root.configure(menu=menu)
            self._menus[""] = menu
        return menu

    def drop_menu(self, label: str) -> None:
        """移除一个菜单（含其所有子菜单）。"""
        for key in [k for k in self._menus if k == label or k.startswith(label + "/")]:
            try:
                self._menus[key].destroy()
            except tk.TclError:
                pass
            del self._menus[key]
        if label in self._menu_order:
            self._menu_order.remove(label)
        if label == "" and self._menus.get("") is None:
            self.root.configure(menu="")

    def drop_menus(self) -> Callable[[], None]:
        """返回一个撤销函数，用于把整棵菜单树一并拆掉。"""

        def dispose() -> None:
            for key in list(self._menus):
                try:
                    self._menus[key].destroy()
                except tk.TclError:
                    pass
            self._menus.clear()
            self._menu_order.clear()
            try:
                self.root.configure(menu="")
            except tk.TclError:
                pass

        return dispose

    def menu(self, label: str) -> tk.Menu:
        """取（或创建）一个顶层菜单。"""
        menu = self._menus.get(label)
        if menu is None:
            menu = tk.Menu(self.menubar, tearoff=False)
            self.menubar.add_cascade(label=label, menu=menu)
            self._menus[label] = menu
            self._menu_order.append(label)
        return menu

    def submenu(self, parent: str, label: str) -> tk.Menu:
        """取（或创建）一个子菜单，挂在 ``parent`` 菜单下。"""
        key = f"{parent}/{label}"
        menu = self._menus.get(key)
        if menu is None:
            menu = tk.Menu(self.menu(parent), tearoff=False)
            self.menu(parent).add_cascade(label=label, menu=menu)
            self._menus[key] = menu
        return menu

    # ------------------------------------------------------------------ 工具栏
    def add_toolbar_button(
        self, text: str, command: Callable[[], Any], tip: str = ""
    ) -> Callable[[], None]:
        """在工具栏加一个按钮。

        **返回撤销函数**，由调用方用 ``ctx.effect`` 登记——这样按钮的生命周期
        跟随调用它的插件，而不是窗口服务。
        """
        button = ttk.Button(
            self.toolbar, text=text, command=command, width=len(text) + 2
        )
        button.pack(side="left", padx=2)
        drop_tip = self.attach_tooltip(button, tip) if tip else None

        def dispose() -> None:
            if drop_tip is not None:
                drop_tip()
            try:
                button.destroy()
            except tk.TclError:
                pass

        return dispose

    def add_toolbar_separator(self) -> Callable[[], None]:
        sep = ttk.Separator(self.toolbar, orient="vertical")
        sep.pack(side="left", fill="y", padx=6)

        def dispose() -> None:
            if sep.winfo_exists():
                sep.destroy()

        return dispose

    # ------------------------------------------------------------------ 侧栏
    def add_pane(self, name: str, widget: Any, *, width: int = 240) -> Callable[[], None]:
        """注册一个可显隐的侧栏（目录、书签等），返回撤销函数。

        与工具栏按钮同理：生命周期归调用方插件所有。
        """
        self._panes[name] = (widget, width)

        def dispose() -> None:
            self.hide_pane(name)
            self._visible.discard(name)
            self._panes.pop(name, None)
            try:
                widget.destroy()
            except tk.TclError:
                pass

        return dispose

    def pane_visible(self, name: str) -> bool:
        """显隐状态由本服务自己记账。

        不用 ``winfo_ismapped``：窗口在 ``withdraw()`` 状态下（测试环境常见）
        所有子控件都未映射，会一直判成隐藏。
        """
        return name in self._visible and name in self._panes

    def show_pane(self, name: str) -> None:
        entry = self._panes.get(name)
        if not entry or self.pane_visible(name):
            return
        widget, width = entry
        # 侧栏固定插在正文左侧
        self.body.insert(0, widget, weight=0)
        widget.configure(width=width)
        self._visible.add(name)

    def hide_pane(self, name: str) -> None:
        entry = self._panes.get(name)
        if not entry or not self.pane_visible(name):
            return
        try:
            self.body.forget(entry[0])
        except tk.TclError:
            pass
        self._visible.discard(name)

    def toggle_pane(self, name: str) -> bool:
        if self.pane_visible(name):
            self.hide_pane(name)
            return False
        self.show_pane(name)
        return True

    # ------------------------------------------------------------------ 资源
    def bind(self, sequence: str, handler: Callable[[Any], Any]) -> Callable[[], None]:
        """绑定全局快捷键，返回撤销函数（已由 Fiber 托管）。"""
        self.root.bind_all(sequence, handler)
        return lambda: self.root.unbind_all(sequence)

    def after(self, delay_ms: int, callback: Callable[[], Any]) -> str:
        """安排一次延时执行。

        定时器 id 记在 :attr:`_after_ids` 里，窗口关闭或服务卸载时统一取消，
        因此不会在 Tk 主循环里留下指向已销毁控件的回调。
        """

        def wrapper() -> None:
            self._after_ids.discard(timer_id)
            callback()

        timer_id = self.root.after(delay_ms, wrapper)
        self._after_ids.add(timer_id)
        return timer_id

    def cancel_after(self, timer_id: str) -> None:
        if timer_id not in self._after_ids:
            return
        try:
            self.root.after_cancel(timer_id)
        except tk.TclError:
            pass
        self._after_ids.discard(timer_id)

    def cancel_all_timers(self) -> None:
        for timer_id in list(self._after_ids):
            try:
                self.root.after_cancel(timer_id)
            except tk.TclError:
                pass
        self._after_ids.clear()

    @staticmethod
    def attach_tooltip(widget: ttk.Widget, text: str) -> Callable[[], None]:
        """给控件挂一个跟随鼠标的提示气泡。"""
        tooltip = tk.Toplevel(widget)
        tooltip.withdraw()
        tooltip.overrideredirect(True)
        ttk.Label(tooltip, text=text, padding=4, relief="solid").pack()

        def show(_event: Any) -> None:
            tooltip.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + 32}")
            tooltip.deiconify()

        def hide(_event: Any) -> None:
            tooltip.withdraw()

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)
        return lambda: tooltip.destroy()

    # ------------------------------------------------------------------ 控制
    def set_title(self, text: str) -> None:
        self.root.title(text or APP_NAME)

    def exists(self) -> bool:
        try:
            return bool(self.root.winfo_exists())
        except tk.TclError:
            return False

    def request_close(self) -> None:
        """统一的关闭入口：广播事件后销毁窗口。"""
        try:
            self.ctx.settings.update(window_geometry=self.root.geometry())
        except tk.TclError:
            pass
        self.ctx.emit(events.APP_CLOSE)
        self.cancel_all_timers()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        self.root.mainloop()


__all__ = ["WindowService"]

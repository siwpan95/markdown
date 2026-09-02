"""应用装配器。

这个文件的职责被压缩到只剩一件事：**把服务和插件装进一个 Context**。

重构前它是 600 多行的「上帝对象」，自己管窗口、菜单、渲染、查找、状态栏、
自动重载、导出……任何一处改动都要在这一个文件里找位置。现在：

    main.py ──> app.create_context(root)
                    ├─ 6 个服务（settings / themes / documents / renderer /
                    │            backends / window）
                    ├─ 3 个后端插件
                    └─ 9 个功能插件（viewer / status / find / toc / appearance /
                                   auto-reload / recent-files / exporter / shell）
                 └─ emit app/ready ──> 各插件完成各自的初始化
                 └─ window.run()     ──> Tk 主循环

装配顺序是**显式**的，但依赖关系是**隐式**的：Cordis 负责按 ``inject`` 推导
加载时机，这里只保证「shell 最后」这一条顺序约束。
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Iterable

from cordis import Context

from . import events
from .core.config import APP_NAME, VERSION
from .plugins import PLUGIN_ORDER
from .services import (
    BackendService,
    DocumentService,
    RenderService,
    SettingsService,
    ThemeService,
    WindowService,
)

#: 服务的注册顺序；真实依赖由各自的 ``inject`` 声明，Cordis 自动编排
SERVICE_ORDER = (
    SettingsService,
    ThemeService,
    DocumentService,
    RenderService,
    WindowService,
    BackendService,
)


def create_context(
    root: tk.Tk,
    *,
    settings: dict[str, Any] | None = None,
    plugins: Iterable[Any] | None = None,
    extra_plugins: Iterable[Any] = (),
) -> Context:
    """创建一个装配好的 Cordis 上下文。

    :param root: Tk 根窗口，交给 ``window`` 服务托管
    :param settings: 覆盖磁盘上的用户设置（命令行参数优先级更高）
    :param plugins: 自定义插件列表；为 ``None`` 时使用 :data:`.plugins.PLUGIN_ORDER`
    :param extra_plugins: 在内置插件之后追加的插件
    """
    ctx = Context()

    for service in SERVICE_ORDER:
        config: Any = None
        if service is SettingsService:
            config = settings
        elif service is WindowService:
            config = {"root": root}
        ctx.plugin(service, config)

    for plugin in (PLUGIN_ORDER if plugins is None else plugins):
        ctx.plugin(plugin)
    for plugin in extra_plugins:
        ctx.plugin(plugin)

    return ctx


def create_app(
    initial_file: str | None = None,
    **kwargs: Any,
) -> Context:
    """创建窗口并装配全部插件，返回可用于测试的上下文。

    返回的 :class:`~cordis.Context` 上可以直接取到所有服务
    （``ctx.documents`` / ``ctx.themes`` / ``ctx.window`` …），测试代码因此
    不需要通过 GUI 就能验证行为。
    """
    root = tk.Tk()
    ctx = create_context(root, **kwargs)
    ctx.emit(events.APP_READY, initial_file)
    return ctx


def main(initial_file: str | None = None) -> int:
    """启动图形界面。"""
    ctx = create_app(initial_file)
    ctx.window.run()
    return 0


#: 供外部引用
__version__ = VERSION
APP_TITLE = APP_NAME

__all__ = ["SERVICE_ORDER", "create_app", "create_context", "main"]

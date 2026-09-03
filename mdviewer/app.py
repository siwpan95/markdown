"""应用装配器。

这个文件的职责被压缩到只剩一件事：**把服务和插件装进一个 Context**。

重构前它是 600 多行的「上帝对象」，自己管窗口、菜单、渲染、查找、状态栏、
自动重载、导出……任何一处改动都要在这一个文件里找位置。现在：

    main.py ──> app.create_context(root)
                    ├─ 6 个服务（settings / themes / documents / renderer /
                    │            backends / window）
                    ├─ 3 个后端插件
                    └─ 功能插件：默认按 PLUGIN_ORDER 加载，
                       传了 config_file 时改由 loader 按配置声明加载
                 └─ emit app/ready ──> 各插件完成各自的初始化
                 └─ window.run()     ──> Tk 主循环

两种装配方式：

* **默认**：``PLUGIN_ORDER`` 里写死顺序，改代码即改行为；
* **配置驱动**：传 ``config_file``（yml/json/toml），功能插件的增删启停都在
  配置文件里，运行时改配置只重建受影响的子树。

服务与后端插件两者都走代码路径——它们是平台，不是可选项；配置只负责
「功能插件装哪些、怎么配」，这条界线让配置文件保持短小可读。
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any, Iterable

from cordis import Context
from cordis.loader import Loader
from cordis.loader.config import find_config_file

from . import events
from .core.config import APP_NAME, VERSION
from .plugins import BACKEND_PLUGINS, FEATURE_PLUGINS, PLUGIN_ORDER
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

#: 项目根目录，作为 loader 解析相对路径的基准
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _register_builtins(loader: Loader) -> None:
    """把内置服务与插件登记成短名，供配置文件引用。

    注册后配置里可以写 ``name: toc`` 而不是 ``name: mdviewer.plugins.toc``。
    """
    from .plugins import (
        appearance,
        auto_reload,
        backend_plaintext,
        backend_tkhtmlview,
        backend_tkinterweb,
        exporter,
        find,
        hmr as hmr_plugin,
        recent_files,
        shell,
        status,
        toc,
        viewer,
    )

    loader.builtins.update(
        {
            "settings": SettingsService,
            "themes": ThemeService,
            "documents": DocumentService,
            "renderer": RenderService,
            "window": WindowService,
            "backends": BackendService,
            "viewer": viewer,
            "shell": shell,
            "toc": toc,
            "find": find,
            "status": status,
            "appearance": appearance,
            "auto-reload": auto_reload,
            "recent-files": recent_files,
            "exporter": exporter,
            "hmr": hmr_plugin,
            "backend/tkinterweb": backend_tkinterweb,
            "backend/tkhtmlview": backend_tkhtmlview,
            "backend/plaintext": backend_plaintext,
        }
    )


def create_context(
    root: tk.Tk,
    *,
    settings: dict[str, Any] | None = None,
    config_file: str | Path | None = None,
    plugins: Iterable[Any] | None = None,
    extra_plugins: Iterable[Any] = (),
    watch: bool = False,
) -> Context:
    """创建一个装配好的 Cordis 上下文。

    :param root: Tk 根窗口，交给 ``window`` 服务托管
    :param settings: 覆盖磁盘上的用户设置（命令行参数优先级更高）
    :param config_file: 配置文件路径；给出时功能插件改由 loader 声明式加载
    :param plugins: 完全自定义的功能插件列表；给出时忽略 ``config_file``
    :param extra_plugins: 在内置插件之后追加的插件
    :param watch: 是否启用热替换（开发期用）
    """
    ctx = Context()

    # 1) 平台：服务 + 渲染后端，始终由代码装配
    if config_file is not None or plugins is not None:
        ctx.plugin(Loader, {"base_url": str(PROJECT_ROOT), "logs": True})
        _register_builtins(ctx.loader)

    for service in SERVICE_ORDER:
        config: Any = None
        if service is SettingsService:
            config = settings
        elif service is WindowService:
            config = {"root": root}
        ctx.plugin(service, config)

    for plugin in BACKEND_PLUGINS:
        ctx.plugin(plugin)

    # 2) 功能插件：默认顺序 / 自定义列表 / 配置文件
    if plugins is not None:
        for plugin in plugins:
            ctx.plugin(plugin)
    elif config_file is not None:
        ctx.loader.load(config_file)
    else:
        for plugin in FEATURE_PLUGINS:
            ctx.plugin(plugin)

    for plugin in extra_plugins:
        ctx.plugin(plugin)

    if watch:
        from .plugins.hmr import apply as hmr_plugin

        ctx.plugin(hmr_plugin)

    return ctx


def create_app(
    initial_file: str | None = None,
    **kwargs: Any,
) -> Context:
    """创建窗口并装配全部插件，返回可用于测试的上下文。

    返回的 :class:`~cordis.Context` 上可以直接取到所有服务
    （``ctx.documents`` / ``ctx.themes`` / ``ctx.window`` / ``ctx.loader`` …），
    测试代码因此不需要通过 GUI 就能验证行为。
    """
    root = tk.Tk()
    ctx = create_context(root, **kwargs)
    ctx.emit(events.APP_READY, initial_file)
    return ctx


def resolve_config_file(explicit: str | Path | None = None) -> Path | None:
    """决定用哪份配置：显式指定优先，否则在项目根自动查找。"""
    if explicit:
        return Path(explicit)
    return find_config_file(PROJECT_ROOT)


def main(initial_file: str | None = None, **kwargs: Any) -> int:
    """启动图形界面。"""
    ctx = create_app(initial_file, **kwargs)
    ctx.window.run()
    return 0


#: 供外部引用
__version__ = VERSION
APP_TITLE = APP_NAME

__all__ = [
    "BACKEND_PLUGINS",
    "FEATURE_PLUGINS",
    "PLUGIN_ORDER",
    "PROJECT_ROOT",
    "SERVICE_ORDER",
    "create_app",
    "create_context",
    "main",
    "resolve_config_file",
]

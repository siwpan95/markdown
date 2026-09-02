"""Markdown Viewer —— 基于 Cordis 插件架构的 Tkinter Markdown 查看器。

包内分四层::

    cordis/     时空可组合性运行时（Context / Fiber / Service / effect / inject）
    core/       纯逻辑：配置、主题、文档、渲染、高亮、导出（不依赖 Tk）
    services/   Cordis 服务：settings / themes / documents / renderer
                / backends / window
    plugins/    Cordis 插件：viewer / shell / toc / find / status
                / appearance / auto-reload / recent-files / exporter
                + 三个渲染后端插件

``app.create_context()`` 是唯一需要知道“装了哪些插件”的地方；插件之间只通过
``inject`` 声明依赖、通过 :mod:`mdviewer.events` 里的事件通信。
"""

from .core.config import APP_NAME, VERSION as __version__

__all__ = ["APP_NAME", "__version__", "create_app", "create_context", "main"]


def __getattr__(name: str):
    """延迟导入装配器，避免无 GUI 环境下导入 tkinter。"""
    if name in ("create_app", "create_context", "main"):
        from . import app

        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""Cordis 服务层。

每个服务占据一个稳定的上下文键，插件通过 ``inject`` 声明依赖：

===================  ======================================================
``ctx.settings``     用户偏好的读写与持久化，带变更广播
``ctx.themes``       当前主题与正文字号（不碰 Tk 控件）
``ctx.documents``    当前文档、最近打开列表、外部修改检测
``ctx.renderer``     Markdown → HTML，按档位缓存解析器
``ctx.backends``     渲染后端的注册表（后端本身由插件注册）
``ctx.window``       Tk 窗口骨架与自动清理的资源申请入口
===================  ======================================================

服务的加载顺序由依赖自动推导，不需要在装配代码里手工排列。
"""

from .backends import BackendService, BackendSpec
from .documents import DocumentService
from .renderer import RenderService
from .settings import SettingsService
from .theme import ThemeService
from .window import WindowService

__all__ = [
    "BackendService",
    "BackendSpec",
    "DocumentService",
    "RenderService",
    "SettingsService",
    "ThemeService",
    "WindowService",
]

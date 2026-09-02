"""插件层 —— 一切皆插件。

``app.py`` 按 :data:`PLUGIN_ORDER` 依次 ``ctx.plugin(...)``，剩下的（加载时机、
依赖顺序、卸载清理）全部由 Cordis 接管：

* 服务没准备好时插件处于 ``PENDING``，准备就绪后自动激活；
* 服务被卸载时，依赖它的插件自动停用并逆序清理副作用；
* ``ctx.registry.delete(plugin)`` 可以运行时热插拔任何一个插件。

因为 ``shell`` 必须最后加载（它广播菜单事件给其他插件），顺序在这里显式写死，
其余插件之间没有任何顺序要求。
"""

from .appearance import apply as appearance
from .auto_reload import apply as auto_reload
from .backend_plaintext import apply as backend_plaintext
from .backend_tkhtmlview import apply as backend_tkhtmlview
from .backend_tkinterweb import apply as backend_tkinterweb
from .exporter import apply as exporter
from .find import apply as find
from .recent_files import apply as recent_files
from .shell import apply as shell
from .status import apply as status
from .toc import apply as toc
from .viewer import apply as viewer

#: 内置渲染后端（按优先级注册，创建时自动探测降级）
BACKEND_PLUGINS = (backend_tkinterweb, backend_tkhtmlview, backend_plaintext)

#: 功能插件
FEATURE_PLUGINS = (
    viewer,
    status,
    find,
    toc,
    appearance,
    auto_reload,
    recent_files,
    exporter,
)

#: 完整加载顺序；``shell`` 必须最后
PLUGIN_ORDER = BACKEND_PLUGINS + FEATURE_PLUGINS + (shell,)

__all__ = [
    "BACKEND_PLUGINS",
    "FEATURE_PLUGINS",
    "PLUGIN_ORDER",
    "appearance",
    "auto_reload",
    "backend_plaintext",
    "backend_tkhtmlview",
    "backend_tkinterweb",
    "exporter",
    "find",
    "recent_files",
    "shell",
    "status",
    "toc",
    "viewer",
]

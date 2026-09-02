"""可插拔的渲染后端。

每个后端把 :class:`~mdviewer.core.renderer.RenderResult` 显示到 Tkinter 上，
并向上层暴露统一的查找、跳转、换肤能力。新增后端只需实现本包的
:class:`~mdviewer.backends.base.Backend` 接口，再写一个注册插件
（参考 ``plugins/backend_plaintext.py``）——不需要改动任何既有代码。

选择顺序与降级逻辑已经移到 :class:`~mdviewer.services.backends.BackendService`
（原来的 ``create_backend`` 工厂函数随之删除）：后端按插件注册的 ``priority``
排序，逐个尝试构造，第一个成功的胜出，失败原因记进 ``note`` 供状态栏显示。
"""

from .base import Backend, LinkTarget
from .plaintext_backend import PlainTextBackend
from .tkhtmlview_backend import TkhtmlviewBackend
from .tkinterweb_backend import TkinterWebBackend

#: 菜单与 ``--list-backends`` 使用的简称。
#: 后端类自身的 ``label`` 是状态栏用的完整名（带“增强模式 / 兼容模式”后缀）。
SHORT_LABELS = {
    "auto": "自动",
    "tkinterweb": "TkinterWeb",
    "tkhtmlview": "tkhtmlview",
    "plaintext": "纯文本",
}

__all__ = [
    "Backend",
    "LinkTarget",
    "PlainTextBackend",
    "SHORT_LABELS",
    "TkhtmlviewBackend",
    "TkinterWebBackend",
]

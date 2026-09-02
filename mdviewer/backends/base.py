"""渲染后端抽象接口。

后端负责把 :class:`~mdviewer.renderer.RenderResult` 显示到 Tkinter 上，
并向上层暴露统一的查找、跳转、换肤能力。这样新增渲染器只需实现本文件的接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.renderer import RenderResult
from ..core.theme import Theme


@dataclass
class LinkTarget:
    """一次链接点击的目标。"""

    url: str
    #: 解析成本地路径后的结果（仅当确实是本地文件时非空）
    path: Path | None = None

    @property
    def is_markdown(self) -> bool:
        return (
            self.path is not None
            and self.path.suffix.lower()
            in (".md", ".markdown", ".mdown", ".mkd", ".mkdn", ".mdtxt", ".mdtext")
        )


class Backend(ABC):
    """渲染后端的公共接口。"""

    #: 唯一标识，与设置里的 ``backend`` 字段对应
    key: str = "base"
    #: 菜单/状态栏展示的名称
    label: str = "未知后端"
    #: 是否支持完整 CSS 样式表
    supports_css: bool = False
    #: 是否支持页内查找
    supports_find: bool = False
    #: 是否支持点击标题跳转
    supports_jump: bool = False

    #: 链接点击回调，由应用注入
    on_link: Callable[[LinkTarget], None] | None = None
    #: 当前文档所在目录，用于解析相对链接
    base_dir: Path | None = None

    # ------------------------------------------------------------------ 生命周期
    @abstractmethod
    def __init__(
        self,
        master,
        theme: Theme,
        font_size: int = 14,
        on_link: Callable[[LinkTarget], None] | None = None,
    ) -> None: ...

    @property
    @abstractmethod
    def widget(self):
        """返回用于几何管理的 Tkinter 控件。"""
        ...

    @abstractmethod
    def destroy(self) -> None:
        """销毁内部控件。"""
        ...

    # ------------------------------------------------------------------ 渲染
    @abstractmethod
    def set_content(self, result: RenderResult, base_dir: Path | None = None) -> None:
        """渲染一篇文档。"""
        ...

    def show_message(self, title: str, message: str) -> None:
        """显示一段提示/错误信息，默认实现退化为纯文本。"""
        self.set_content(
            RenderResult(html=f"<h3>{title}</h3><p>{message}</p>", css="")
        )

    # ------------------------------------------------------------------ 外观
    def set_theme(self, theme: Theme) -> None:
        """切换主题；不支持时静默忽略。"""

    def set_font_size(self, size: int) -> None:
        """调整正文字号；不支持时静默忽略。"""

    def set_word_wrap(self, enabled: bool) -> None:
        """开启/关闭自动换行；不支持时静默忽略。"""

    # ------------------------------------------------------------------ 查找
    def find(self, query: str, *, nocase: bool = True) -> int:
        """高亮所有匹配项，返回命中数量。"""
        return 0

    def find_next(self) -> int:
        """跳到下一个匹配项，返回 1 起始的序号（无匹配返回 0）。"""
        return 0

    def find_prev(self) -> int:
        """跳到上一个匹配项，返回 1 起始的序号（无匹配返回 0）。"""
        return 0

    def clear_find(self) -> None:
        """清除查找高亮。"""

    # ------------------------------------------------------------------ 导航
    def scroll_to_text(self, text: str) -> bool:
        """滚动到首次出现 ``text`` 的位置。"""
        return False

    def scroll_to_top(self) -> None:
        """回到顶部。"""

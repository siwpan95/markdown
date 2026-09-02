"""基于 tkhtmlview 的渲染后端（默认后端）。

tkhtmlview 的实现特点（阅读其源码得出，直接决定了本文件的写法）：

* 它不是浏览器内核，而是用 :mod:`html.parser` 把 HTML 翻译成 ``Text`` 的 tag；
* **不解析** ``<style>`` 样式表——CSS 文本会被当成正文显示，所以样式只能写成
  内联 ``style`` 属性（由 :mod:`mdviewer.renderer` 的 simple 档位负责）；
* 只识别 ``color`` ``background-color`` ``font-family`` ``font-size``
  ``text-align`` ``text-decoration`` 六个样式属性；
* 图片 ``src`` 必须是 ``os.path.exists()`` 为真的本地路径，``file://`` 无效；
* 链接点击回调被写死在内部，这里通过重新绑定 tag 事件来接管；
* 字号来自模块级常量 ``tkhtmlview.html_parser.Defs``，因此缩放需要改写它。
"""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from typing import Callable

from ..core.renderer import RenderResult
from ..core.theme import Theme
from .base import Backend, LinkTarget

FIND_TAG = "mdv-find"
JUMP_TAG = "mdv-jump"

#: 基础字号，用于按倍率推算各级标题字号
_BASE_HEADING_RATIO = {"h1": 32 / 14, "h2": 24 / 14, "h3": 18 / 14, "h4": 16 / 14, "h5": 13 / 14, "h6": 10 / 14}


class TkhtmlviewBackend(Backend):
    """把受限 HTML 渲染到 tkhtmlview 的 ``HTMLLabel`` 上。"""

    key = "tkhtmlview"
    label = "tkhtmlview（兼容模式）"
    supports_css = False
    supports_find = True
    supports_jump = True

    def __init__(
        self,
        master,
        theme: Theme,
        font_size: int = 14,
        on_link: Callable[[LinkTarget], None] | None = None,
    ) -> None:
        from tkhtmlview import HTMLLabel  # 延迟导入，便于本模块被静态检查

        self.theme = theme
        self.font_size = font_size
        self.on_link = on_link
        self._matches: list[str] = []
        self._cursor = 0
        self._text = HTMLLabel(master, background=theme.body_bg)
        self._apply_font_size(font_size)
        self.show_message(
            "欢迎使用 Markdown Viewer",
            "点击工具栏的“打开”按钮，或直接把 .md 文件拖到命令行参数上启动。",
        )

    # ------------------------------------------------------------------ 基础
    @property
    def widget(self):
        return self._text

    @property
    def text(self):
        """底层 ``Text`` 控件，供需要文本索引的能力使用。"""
        return self._text

    def destroy(self) -> None:
        try:
            self._text.destroy()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 渲染
    def set_content(self, result: RenderResult, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir
        self._matches = []
        self._cursor = 0
        # 必须在解析前改写默认值：字号与前景色都来自模块级常量
        self._apply_default_colors(self.theme)
        self._apply_font_size(self.font_size)
        self._text.set_html(result.html)
        self._text.configure(background=self.theme.body_bg)
        self._configure_find_tag()
        self._rebind_links()

    def show_message(self, title: str, message: str) -> None:
        self._text.set_html(f"<h2>{title}</h2><p>{message}</p>")

    # ------------------------------------------------------------------ 外观
    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self._apply_default_colors(theme)
        try:
            self._text.configure(background=theme.body_bg)
        except Exception:  # noqa: BLE001
            pass
        self._configure_find_tag()

    def set_font_size(self, size: int) -> None:
        self.font_size = size
        self._apply_font_size(size)

    def set_word_wrap(self, enabled: bool) -> None:
        try:
            self._text.configure(wrap="word" if enabled else "none")
        except Exception:  # noqa: BLE001
            pass

    def _apply_font_size(self, size: int) -> None:
        """改写 tkhtmlview 的模块级字号常量以实现整体缩放。"""
        try:
            from tkhtmlview import html_parser

            html_parser.Defs.FONT_SIZE = int(size)
            html_parser.Defs.HEADINGS_FONT_SIZE = {
                tag: max(8, int(round(size * ratio)))
                for tag, ratio in _BASE_HEADING_RATIO.items()
            }
        except Exception:  # noqa: BLE001 - 版本不兼容时退化为默认字号
            pass

    def _apply_default_colors(self, theme: Theme) -> None:
        """改写 tkhtmlview 的默认前景色。

        ``tkhtmlview.html_parser.DEFAULT_STACK`` 把默认前景色硬编码为 ``black``，
        且每个元素都会被显式赋上该值，导致深色主题下正文不可见。
        """
        try:
            from tkhtmlview import html_parser

            config = html_parser.DEFAULT_STACK.get("config")
            if isinstance(config, dict) and "foreground" in config:
                config["foreground"] = [("__DEFAULT__", theme.body_fg)]
        except Exception:  # noqa: BLE001
            pass

    def _configure_find_tag(self) -> None:
        try:
            self._text.tag_configure(
                FIND_TAG, background=self.theme.find_bg, foreground=self.theme.find_fg
            )
            self._text.tag_configure(JUMP_TAG, background=self.theme.quote_bg)
            self._text.tag_raise(FIND_TAG)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 链接
    def _rebind_links(self) -> None:
        """用应用自己的回调替换 tkhtmlview 内置的“用浏览器打开”行为。"""
        parser = getattr(self._text, "html_parser", None)
        slots = getattr(parser, "hlink_slots", None) or []
        for slot in slots:
            url = getattr(slot, "URL", "") or ""
            try:
                self._text.tag_bind(
                    slot.tag_name, "<Button-1>", lambda _e, u=url: self._handle_link(u)
                )
                self._text.tag_bind(
                    slot.tag_name, "<Enter>", lambda _e: self._text.configure(cursor="hand2")
                )
                self._text.tag_bind(
                    slot.tag_name, "<Leave>", lambda _e: self._text.configure(cursor="")
                )
            except Exception:  # noqa: BLE001
                continue

    def _handle_link(self, url: str) -> None:
        if not url:
            return
        target = LinkTarget(url=url, path=self._resolve_path(url))
        if self.on_link is not None:
            self.on_link(target)
        elif target.path is not None and target.path.is_file():
            try:
                os.startfile(str(target.path))  # type: ignore[attr-defined]
            except OSError:
                webbrowser.open(target.path.as_uri())
        else:
            webbrowser.open(url)

    def _resolve_path(self, url: str) -> Path | None:
        """把链接解析为本地文件路径；不是本地文件时返回 ``None``。"""
        if not url or re_match_remote(url):
            return None
        candidate = Path(url)
        if not candidate.is_absolute() and self.base_dir is not None:
            candidate = self.base_dir / url
        try:
            resolved = candidate.resolve()
        except (OSError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    # ------------------------------------------------------------------ 查找
    def find(self, query: str, *, nocase: bool = True) -> int:
        self.clear_find()
        if not query:
            return 0
        start = "1.0"
        while True:
            pos = self._text.search(query, start, stopindex="end", nocase=nocase)
            if not pos:
                break
            end = f"{pos}+{len(query)}c"
            self._matches.append(pos)
            self._text.tag_add(FIND_TAG, pos, end)
            start = end
            if len(self._matches) > 10_000:  # 防止超大文档卡死
                break
        # -1 表示尚未选中任何一项，下一次 find_next 才会走到第 1 个
        self._cursor = -1
        return len(self._matches)

    def find_next(self) -> int:
        return self._step(1)

    def find_prev(self) -> int:
        return self._step(-1)

    def _step(self, delta: int) -> int:
        if not self._matches:
            return 0
        self._cursor = (self._cursor + delta) % len(self._matches)
        return self._reveal(self._cursor)

    def _reveal(self, index: int) -> int:
        pos = self._matches[index]
        self._text.see(pos)
        self._text.tag_remove(JUMP_TAG, "1.0", "end")
        self._text.tag_add(JUMP_TAG, pos, f"{pos}+1l")
        self._text.tag_raise(FIND_TAG)
        return index + 1

    def clear_find(self) -> None:
        self._matches = []
        self._cursor = 0
        try:
            self._text.tag_remove(FIND_TAG, "1.0", "end")
            self._text.tag_remove(JUMP_TAG, "1.0", "end")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 导航
    def scroll_to_text(self, text: str) -> bool:
        if not text:
            return False
        pos = self._text.search(text, "1.0", stopindex="end")
        if not pos:
            return False
        self._text.see(pos)
        self._text.tag_remove(JUMP_TAG, "1.0", "end")
        self._text.tag_add(JUMP_TAG, pos, f"{pos}+1l")
        self._text.tag_raise(FIND_TAG)
        return True

    def scroll_to_top(self) -> None:
        self._text.yview_moveto(0.0)


def re_match_remote(url: str) -> bool:
    """判断是否是网络协议（相对路径不适合交给浏览器打开）。"""
    lowered = url.lower()
    return lowered.startswith(("http://", "https://", "ftp://", "mailto:", "//"))

"""纯文本兜底后端。

当 tkhtmlview 与 TkinterWeb 都不可用时（例如缺少 Pillow / requests，
或 Tkhtml 二进制缺失），仍然可以用只读的 ``Text`` 显示 Markdown 原文。
它同时也是一个“源码视图”，方便核对 Markdown 标记。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..core.renderer import RenderResult
from ..core.theme import Theme
from .base import Backend

FIND_TAG = "mdv-find"


class PlainTextBackend(Backend):
    """以等宽字体只读显示 Markdown 源码。"""

    key = "plaintext"
    label = "纯文本（源码视图）"
    supports_css = False
    supports_find = True
    supports_jump = True

    def __init__(
        self,
        master,
        theme: Theme,
        font_size: int = 14,
        on_link: Callable | None = None,
    ) -> None:
        self.theme = theme
        self.font_size = font_size
        self.on_link = on_link
        self._matches: list[str] = []
        self._cursor = 0
        self._raw = ""

        self._container = ttk.Frame(master)
        self._text = tk.Text(
            self._container,
            wrap="word",
            background=theme.body_bg,
            foreground=theme.body_fg,
            insertbackground=theme.body_fg,
            relief="flat",
            borderwidth=0,
            padx=16,
            pady=12,
            font=("Consolas", max(font_size - 2, 8)),
        )
        self._scroll = ttk.Scrollbar(
            self._container, orient="vertical", command=self._text.yview
        )
        self._text.configure(yscrollcommand=self._scroll.set)
        self._scroll.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)
        self._text.configure(state="disabled")
        self._apply_theme(theme)

    # ------------------------------------------------------------------ 基础
    @property
    def widget(self):
        return self._container

    def destroy(self) -> None:
        try:
            self._container.destroy()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 渲染
    def set_content(self, result: RenderResult, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir
        self._raw = result.html
        self._matches = []
        self._cursor = 0
        self._replace(self._raw)

    def show_message(self, title: str, message: str) -> None:
        self._replace(f"{title}\n\n{message}")

    def _replace(self, content: str) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("1.0", content)
        self._text.configure(state="disabled")
        self._text.yview_moveto(0.0)

    # ------------------------------------------------------------------ 外观
    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self._apply_theme(theme)

    def set_font_size(self, size: int) -> None:
        self.font_size = size
        self._text.configure(font=("Consolas", max(size - 2, 8)))

    def set_word_wrap(self, enabled: bool) -> None:
        self._text.configure(wrap="word" if enabled else "none")

    def _apply_theme(self, theme: Theme) -> None:
        self._text.configure(
            background=theme.body_bg,
            foreground=theme.body_fg,
            insertbackground=theme.body_fg,
        )
        self._text.tag_configure(
            FIND_TAG, background=theme.find_bg, foreground=theme.find_fg
        )
        self._text.tag_raise(FIND_TAG)

    # ------------------------------------------------------------------ 查找
    def _search(self, query: str, nocase: bool) -> None:
        start = "1.0"
        while True:
            pos = self._text.search(query, start, stopindex="end", nocase=nocase)
            if not pos:
                break
            end = f"{pos}+{len(query)}c"
            self._matches.append(pos)
            self._text.tag_add(FIND_TAG, pos, end)
            start = end
            if len(self._matches) > 10_000:
                break

    def find(self, query: str, *, nocase: bool = True) -> int:
        self.clear_find()
        if not query:
            return 0
        self._search(query, nocase)
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
        pos = self._matches[self._cursor]
        self._text.see(pos)
        return self._cursor + 1

    def clear_find(self) -> None:
        self._matches = []
        self._cursor = 0
        try:
            self._text.tag_remove(FIND_TAG, "1.0", "end")
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
        return True

    def scroll_to_top(self) -> None:
        self._text.yview_moveto(0.0)

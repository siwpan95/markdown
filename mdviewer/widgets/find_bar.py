"""页内查找栏。

查找能力由后端提供，本组件只负责输入与导航交互。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class FindBar(ttk.Frame):
    """带匹配计数与前后导航的查找条。"""

    def __init__(
        self,
        master,
        on_query: Callable[[str, bool], int],
        on_next: Callable[[], int],
        on_prev: Callable[[], int],
        on_close: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=(6, 4))
        self._on_query = on_query
        self._on_next = on_next
        self._on_prev = on_prev
        self._on_close = on_close

        self.query = tk.StringVar()
        self.nocase = tk.BooleanVar(value=True)
        self._count = 0

        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="查找:").grid(row=0, column=0, padx=(0, 6))

        self._entry = ttk.Entry(self, textvariable=self.query)
        self._entry.grid(row=0, column=1, sticky="ew")
        self._entry.bind("<Return>", lambda _e: self.next_match())
        self._entry.bind("<Shift-Return>", lambda _e: self.prev_match())
        self._entry.bind("<Escape>", lambda _e: self._on_close())
        self.query.trace_add("write", lambda *_: self._run_query())

        self._label = ttk.Label(self, text="无匹配", width=14)
        self._label.grid(row=0, column=2, padx=6)

        ttk.Button(self, text="上一个", width=7, command=self.prev_match).grid(
            row=0, column=3, padx=2
        )
        ttk.Button(self, text="下一个", width=7, command=self.next_match).grid(
            row=0, column=4, padx=2
        )
        ttk.Checkbutton(self, text="忽略大小写", variable=self.nocase,
                        command=self._run_query).grid(row=0, column=5, padx=6)
        ttk.Button(self, text="关闭", width=6, command=self._on_close).grid(
            row=0, column=6, padx=(6, 0)
        )

    # ------------------------------------------------------------------ 行为
    def focus_entry(self) -> None:
        """聚焦并全选输入框内容。"""
        self._entry.focus_set()
        self._entry.select_range(0, "end")

    def close(self) -> None:
        """隐藏查找栏并通知外部清理高亮。

        查找栏由 pack 管理（不是 grid），因此这里用 ``pack_forget``。
        """
        self.pack_forget()
        self._on_close()

    def _run_query(self) -> None:
        text = self.query.get()
        if not text:
            self._count = 0
            self._label.configure(text="无匹配")
            self._on_query("", self.nocase.get())
            return
        self._count = self._on_query(text, self.nocase.get())
        self._update_label(0)

    def next_match(self) -> None:
        if not self.query.get():
            return
        self._update_label(self._on_next())

    def prev_match(self) -> None:
        if not self.query.get():
            return
        self._update_label(self._on_prev())

    def _update_label(self, index: int) -> None:
        if self._count <= 0:
            self._label.configure(text="无匹配")
            return
        current = index if index > 0 else 1
        self._label.configure(text=f"{current}/{self._count}")

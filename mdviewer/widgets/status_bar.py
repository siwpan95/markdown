"""底部状态栏。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class StatusBar(ttk.Frame):
    """左侧显示文档信息，右侧显示渲染后端提示。"""

    def __init__(self, master) -> None:
        super().__init__(master, padding=(8, 3))
        self.columnconfigure(0, weight=1)

        self._left = tk.StringVar(value="就绪")
        self._right = tk.StringVar(value="")

        ttk.Label(self, textvariable=self._left, anchor="w").grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Label(self, textvariable=self._right, anchor="e", foreground="#6a737d").grid(
            row=0, column=1, sticky="e"
        )

    def set_left(self, text: str) -> None:
        self._left.set(text)

    def set_right(self, text: str) -> None:
        self._right.set(text)

    def set(self, left: str = "", right: str = "") -> None:
        if left:
            self.set_left(left)
        self.set_right(right)

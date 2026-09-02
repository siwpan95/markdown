"""目录侧栏。

数据来自 Python-Markdown ``toc`` 扩展的 ``toc_tokens``。受限后端（tkhtmlview）
无法按锚点跳转，因此统一用“标题文本”定位：``Text.search`` + ``see``。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class TocPanel(ttk.Frame):
    """可折叠、可过滤的目录树。"""

    def __init__(
        self,
        master,
        on_select: Callable[[str], None],
        padding: int = 6,
    ) -> None:
        super().__init__(master, padding=padding)
        self._on_select = on_select
        self._items: list[tuple[str, int, str]] = []  # (iid, level, heading 文本)
        self._filter = tk.StringVar(value="")
        self._filter.trace_add("write", lambda *_: self._apply_filter())

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        filter_row = ttk.Frame(self)
        filter_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        filter_row.columnconfigure(0, weight=1)
        ttk.Entry(filter_row, textvariable=self._filter).grid(row=0, column=0, sticky="ew")

        tree_frame = ttk.Frame(self)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            tree_frame, show="tree", selectmode="browse", height=20
        )
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", lambda _e: self._emit_current())

    # ------------------------------------------------------------------ 数据
    def clear(self) -> None:
        """清空目录。"""
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._items = []

    def populate(self, tokens: list[dict], *, max_level: int = 6) -> None:
        """用 ``toc_tokens`` 重建目录树。"""
        self.clear()
        self._collect(tokens, parent="", max_level=max_level)
        self._apply_filter()
        children = self._tree.get_children()
        if children:
            self._tree.selection_set(children[0])

    def _collect(self, tokens: list[dict], parent: str, max_level: int) -> None:
        for token in tokens:
            level = int(token.get("level", 1))
            name = (token.get("name") or "").strip()
            if not name or level > max_level:
                continue
            indent = "　" * max(level - 1, 0)
            iid = self._tree.insert(parent, "end", text=f"{indent}{name}", open=True)
            self._items.append((iid, level, name))
            children = token.get("children") or []
            if children:
                self._collect(children, iid, max_level)

    # ------------------------------------------------------------------ 交互
    def _on_tree_select(self, _event=None) -> None:
        self._emit_current()

    def _emit_current(self) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        found = next((item for item in self._items if item[0] == selection[0]), None)
        if found is not None:
            self._on_select(found[2])

    def _apply_filter(self) -> None:
        """按关键字过滤目录项（保留父级，避免子树被隐藏）。"""
        keyword = self._filter.get().strip().lower()
        if not keyword:
            for iid, _level, _name in self._items:
                self._tree.item(iid, tags=())
            self._tree.tag_configure("hidden", foreground="")
            self._show_all()
            return

        visible = {
            iid for iid, _level, name in self._items if keyword in name.lower()
        }
        # 把命中项的祖先也显示出来
        for iid in list(visible):
            parent = self._tree.parent(iid)
            while parent:
                visible.add(parent)
                parent = self._tree.parent(parent)

        for iid, _level, _name in self._items:
            self._tree.item(iid, tags=("hidden",) if iid not in visible else ())
        self._tree.tag_configure("hidden", foreground="#9aa0a6")

    def _show_all(self) -> None:
        for iid, _level, _name in self._items:
            self._tree.item(iid, tags=())

"""文档服务 —— ``ctx.documents``。

负责“当前打开的是哪个文件”这一状态，以及最近打开列表。渲染与展示不在这里——
:mod:`mdviewer.plugins.viewer` 监听 :data:`~mdviewer.events.DOC_OPEN` 之后接管。

把文档状态收敛成服务的好处是：菜单里加一个“打开最近的第 3 个文件”、自动重载
插件检测到修改、命令行启动时预加载文件，走的是同一条路径，不需要各自去碰
``Document.load`` 和 ``settings.add_recent``。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from cordis import Service

from .. import events
from ..core.config import FILE_TYPES, MAX_RECENT_FILES
from ..core.document import Document, compute_stats

if TYPE_CHECKING:  # pragma: no cover
    from cordis import Context


class DocumentService(Service):
    """当前文档与最近打开列表。"""

    name = "documents"
    inject = ["settings"]

    def __init__(self, ctx: "Context", config: Any = None) -> None:
        super().__init__(ctx, config)
        self.current: Document | None = None
        self._mtime: float = 0.0

    # ------------------------------------------------------------------ 查询
    @property
    def path(self) -> Path | None:
        return self.current.path if self.current else None

    @property
    def directory(self) -> Path | None:
        return self.current.directory if self.current else None

    @property
    def text(self) -> str:
        return self.current.text if self.current else ""

    @property
    def is_open(self) -> bool:
        return self.current is not None and not self.current.error

    @property
    def file_types(self) -> tuple:
        return FILE_TYPES

    # ------------------------------------------------------------------ 打开
    def open(self, path: str | Path) -> Document | None:
        """打开一个文件；成功返回 :class:`Document`，失败返回 ``None``。

        两种情况都会广播事件（``document/open`` 或 ``document/error``），
        调用方不需要再判断返回值。
        """
        target = Path(path)
        if not target.is_file():
            self.forget_recent(target)
            self.ctx.emit(events.DOC_ERROR, target, f"文件不存在：\n{target}")
            return None

        document = Document.load(target)
        self.current = document
        if document.error:
            self.ctx.emit(events.DOC_ERROR, target, document.error)
            return None

        self.add_recent(target)
        self._mtime = target.stat().st_mtime
        document.stats = compute_stats(document.text)
        self.ctx.emit(events.DOC_OPEN, document)
        return document

    def reload(self) -> Document | None:
        """重新读取当前文件。"""
        if self.current is None:
            return None
        document = self.open(self.current.path)
        if document is not None:
            self.ctx.emit(events.DOC_RELOADED, document)
        return document

    def close(self) -> None:
        self.current = None
        self._mtime = 0.0

    # ------------------------------------------------------------------ 自动重载
    def has_external_change(self) -> bool:
        """文件在外部被修改过（mtime 变新）时为 ``True``。"""
        if self.current is None or not self.current.path.is_file():
            return False
        try:
            mtime = self.current.path.stat().st_mtime
        except OSError:
            return False
        return bool(self._mtime) and mtime > self._mtime

    def sync_mtime(self) -> None:
        if self.current is not None and self.current.path.is_file():
            try:
                self._mtime = self.current.path.stat().st_mtime
            except OSError:
                pass

    def update_stats(self, toc_tokens: list[dict] | None = None) -> None:
        """按最新渲染结果重算统计信息（标题数来自目录树，比正则更准）。"""
        if self.current is None:
            return
        self.current.stats = compute_stats(self.current.text, toc_tokens)

    # ------------------------------------------------------------------ 最近文件
    def recent_files(self) -> list[str]:
        """返回仍然存在的最近打开路径。"""
        files = self.ctx.settings.get("recent_files") or []
        return [p for p in files if p and Path(p).is_file()][:MAX_RECENT_FILES]

    def add_recent(self, path: str | Path) -> None:
        text = str(Path(path))
        files = list(self.ctx.settings.get("recent_files") or [])
        files = [text] + [p for p in files if p != text]
        self.ctx.settings.update(recent_files=files[:MAX_RECENT_FILES])

    def forget_recent(self, path: str | Path) -> None:
        text = str(Path(path))
        files = list(self.ctx.settings.get("recent_files") or [])
        kept = [p for p in files if p != text]
        if kept != files:
            self.ctx.settings.update(recent_files=kept)

    def clear_recent(self) -> None:
        if self.ctx.settings.get("recent_files"):
            self.ctx.settings.update(recent_files=[])


__all__ = ["DocumentService"]

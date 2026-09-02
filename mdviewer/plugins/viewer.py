"""阅读器插件 —— 把「文档 → 渲染 → 后端」串起来。

这是重构后新增的插件，承担原来 ``MarkdownViewerApp`` 里最杂的那一半职责：
什么时候重新渲染、渲染完通知谁、链接怎么跳、后端不可用时显示什么。

它自己不持有业务状态，只订阅事件并调用服务::

    document/open ──┐
    theme/change ───┤
    view/font-size ─┼──> 重新渲染 ──> backend.set_content ──> document/rendered
    backend/change ─┤
    settings/change ┘
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

from .. import events
from ..core.config import APP_NAME
from ..core.renderer import RenderResult

WELCOME_TITLE = f"欢迎使用 {APP_NAME}"
WELCOME_BODY = "点击“打开”选择 Markdown 文件，或将文件路径作为启动参数传入。"


def apply(ctx: Any, config: Any = None) -> None:
    """装配阅读器。"""
    #: 最近一次渲染结果，供锚点跳转时反查标题文本
    state: dict[str, Any] = {"result": None}

    # ---------------------------------------------------------------- 渲染
    def render_current() -> RenderResult | None:
        """按后端能力渲染当前文档。"""
        backend = ctx.backends.current
        document = ctx.documents.current
        if backend is None or document is None:
            return None

        if backend.key == "plaintext":
            result = ctx.renderer.render_source(document.text)
        else:
            result = ctx.renderer.render_text(
                document.text,
                profile=ctx.backends.profile_for(),
                theme=ctx.themes.current,
                base_dir=document.directory,
                font_size=ctx.themes.font_size,
            )

        backend.set_content(result, base_dir=document.directory)
        backend.set_word_wrap(bool(ctx.settings.get("word_wrap", True)))
        ctx.documents.update_stats(result.toc_tokens)
        state["result"] = result
        ctx.emit(events.DOC_RENDERED, result)
        return result

    def show_welcome() -> None:
        backend = ctx.backends.current
        if backend is not None:
            backend.show_message(WELCOME_TITLE, WELCOME_BODY)

    def refresh_or_welcome() -> None:
        if ctx.documents.is_open:
            render_current()
        else:
            show_welcome()

    # ---------------------------------------------------------------- 事件
    def on_open(document: Any) -> None:
        ctx.window.set_title(f"{document.title} — {APP_NAME}")
        render_current()

    def on_error(path: Path, message: str) -> None:
        ctx.emit(events.STATUS_MESSAGE, str(message).replace("\n", " "))
        backend = ctx.backends.current
        if backend is not None:
            backend.show_message("无法打开文档", message)

    def on_theme_change(theme: Any) -> None:
        backend = ctx.backends.current
        if backend is None:
            return
        backend.set_theme(theme)
        refresh_or_welcome()
        # 后端可能在换肤后改了自己的显示名/降级说明，让状态栏刷新
        ctx.emit(events.BACKEND_CHANGE, backend)

    def on_font_size_change(size: int) -> None:
        backend = ctx.backends.current
        if backend is None:
            return
        backend.set_font_size(size)
        if ctx.documents.is_open:
            render_current()

    def on_backend_change(backend: Any) -> None:
        backend.set_word_wrap(bool(ctx.settings.get("word_wrap", True)))
        refresh_or_welcome()

    def on_settings_change(key: str, value: Any) -> None:
        if key != "word_wrap":
            return
        backend = ctx.backends.current
        if backend is not None:
            backend.set_word_wrap(bool(value))

    def on_jump(heading: str) -> None:
        backend = ctx.backends.current
        if backend is not None:
            backend.scroll_to_text(heading)

    # ---------------------------------------------------------------- 链接
    def jump_to_anchor(anchor_id: str) -> None:
        """受限后端没有锚点概念，退化为按标题文本搜索。"""
        backend = ctx.backends.current
        if backend is None:
            return
        name = _find_heading_name(state["result"], anchor_id)
        backend.scroll_to_text(name or anchor_id.replace("-", " "))

    def on_link(target: Any) -> None:
        url = target.url
        if url.startswith("#"):
            jump_to_anchor(url[1:])
            return
        if target.is_markdown and target.path is not None:
            ctx.documents.open(target.path)
            return
        if target.path is not None and target.path.is_file():
            _open_with_system(target.path)
            return
        webbrowser.open(url)

    # ---------------------------------------------------------------- 启动
    def on_ready(initial_file: Any) -> None:
        ctx.backends.attach(ctx.backends.create())
        if initial_file:
            ctx.documents.open(initial_file)
        else:
            show_welcome()

    ctx.on(events.APP_READY, on_ready)
    ctx.on(events.DOC_OPEN, on_open)
    ctx.on(events.DOC_RELOADED, on_open)
    ctx.on(events.DOC_ERROR, on_error)
    ctx.on(events.THEME_CHANGE, on_theme_change)
    ctx.on(events.FONT_SIZE_CHANGE, on_font_size_change)
    ctx.on(events.BACKEND_CHANGE, on_backend_change)
    ctx.on(events.SETTINGS_CHANGE, on_settings_change)
    ctx.on(events.ACTION_JUMP, on_jump)
    ctx.on(events.LINK_OPEN, on_link)


def _find_heading_name(result: RenderResult | None, anchor_id: str) -> str:
    """在目录树里按 id 找标题文本。"""
    if result is None:
        return ""
    stack = list(result.toc_tokens)
    while stack:
        token = stack.pop()
        if token.get("id") == anchor_id:
            return str(token.get("name") or "")
        stack.extend(token.get("children") or [])
    return ""


def _open_with_system(path: Path) -> None:
    """用系统默认程序打开非 Markdown 的本地文件。"""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError:
        webbrowser.open(path.as_uri())


apply.name = "viewer"
apply.inject = ["settings", "themes", "documents", "renderer", "backends", "window"]

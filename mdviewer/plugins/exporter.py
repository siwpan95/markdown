"""导出插件。

实现两个用户动作：

* :data:`~mdviewer.events.ACTION_EXPORT_HTML` —— 另存为自带样式的独立 HTML；
* :data:`~mdviewer.events.ACTION_OPEN_BROWSER` —— 生成临时 HTML 并用默认
  浏览器打开（浏览器里可再打印成 PDF，比引入重量级 PDF 依赖更划算）。

``shell`` 只负责发出这两个动作，不需要知道导出是怎么实现的。
"""

from __future__ import annotations

from tkinter import filedialog, messagebox
from typing import Any

import webbrowser

from .. import events
from ..core.config import APP_NAME, config_dir
from ..core.exporter import build_standalone_html, export_html


def apply(ctx: Any, config: Any = None) -> None:
    def export() -> None:
        document = ctx.documents.current
        if document is None:
            messagebox.showinfo(APP_NAME, "请先打开一个 Markdown 文件。")
            return
        suggested = document.path.with_suffix(".html")
        target = filedialog.asksaveasfilename(
            title="导出为 HTML",
            defaultextension=".html",
            initialfile=suggested.name,
            initialdir=str(document.directory),
            filetypes=(("HTML 文件", "*.html"), ("所有文件", "*.*")),
        )
        if not target:
            return
        try:
            path = export_html(
                document.text,
                target,
                ctx.themes.current,
                document.directory,
                ctx.themes.font_size,
                title=document.path.stem,
            )
        except OSError as error:
            messagebox.showerror(APP_NAME, f"导出失败：\n{error}")
            return
        ctx.emit(events.STATUS_MESSAGE, f"已导出：{path}")
        if messagebox.askyesno(APP_NAME, "导出完成，是否立即在浏览器中打开？"):
            webbrowser.open(path.as_uri())

    def open_in_browser() -> None:
        document = ctx.documents.current
        if document is None:
            messagebox.showinfo(APP_NAME, "请先打开一个 Markdown 文件。")
            return
        preview_dir = config_dir() / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        target = preview_dir / f"{document.path.stem}.html"
        try:
            target.write_text(
                build_standalone_html(
                    document.path.stem,
                    document.text,
                    ctx.themes.current,
                    document.directory,
                    ctx.themes.font_size,
                ),
                encoding="utf-8",
            )
        except OSError as error:
            messagebox.showerror(APP_NAME, f"生成预览失败：\n{error}")
            return
        webbrowser.open(target.as_uri())
        ctx.emit(events.STATUS_MESSAGE, f"已在浏览器中打开：{target}")

    ctx.on(events.ACTION_EXPORT_HTML, export)
    ctx.on(events.ACTION_OPEN_BROWSER, open_in_browser)


apply.name = "exporter"
apply.inject = ["themes", "documents"]

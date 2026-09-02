"""导出能力：把当前文档另存为独立的 HTML 文件。

导出的文件自带完整 CSS 与 Pygments 样式，可直接双击用浏览器打开，
也可以再让浏览器打印成 PDF——这比引入重量级的 PDF 依赖更稳妥。
"""

from __future__ import annotations

import html as html_mod
from pathlib import Path

from .renderer import RICH, render
from .theme import Theme


def build_standalone_html(
    title: str,
    markdown_text: str,
    theme: Theme,
    base_dir: Path | None = None,
    font_size: int = 14,
) -> str:
    """生成一份自带样式的完整 HTML 文档。

    使用 :data:`~mdviewer.renderer.RICH` 档位：带 CSS class 的高亮 + 外链图片
    转为 ``file://`` 形式，因此在浏览器中也能正常显示本地图片。
    """
    result = render(
        markdown_text,
        profile=RICH,
        theme=theme,
        base_dir=base_dir,
        font_size=font_size,
    )
    safe_title = html_mod.escape(title or "Markdown 文档")
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{safe_title}</title>\n"
        f"<style>{result.css}</style>\n"
        "</head>\n<body>\n"
        f"{result.html}\n"
        "</body>\n</html>\n"
    )


def export_html(
    markdown_text: str,
    target: str | Path,
    theme: Theme,
    base_dir: Path | None = None,
    font_size: int = 14,
    title: str = "",
) -> Path:
    """把文档导出为独立 HTML 文件，返回写入后的路径。"""
    path = Path(target)
    if path.suffix.lower() not in (".html", ".htm"):
        path = path.with_suffix(".html")
    document = build_standalone_html(
        title or path.stem, markdown_text, theme, base_dir, font_size
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path

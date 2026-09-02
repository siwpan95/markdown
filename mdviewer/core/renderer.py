"""Markdown 渲染：把源文件转换为各后端可用的 HTML。

渲染分两种档位（``profile``）：

``rich``
    输出标准 HTML，配合外部 CSS 使用。适用于 tkinterweb 后端与导出的 HTML 文件。

``simple``
    输出“受限 HTML”——只使用 tkhtmlview 认识的标签，且样式全部写成内联
    ``style`` 属性。tkhtmlview 既不支持 ``<style>`` 样式表（会被当成正文显示），
    也不支持 ``blockquote`` / ``hr`` / ``del`` 等标签，因此这里统一做降级替换。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from xml.etree import ElementTree as etree

from .highlight import CodeHighlightExtension, pygments_css
from .theme import Theme, build_css

RICH = "rich"
SIMPLE = "simple"

#: 各档位启用的 Python-Markdown 内置扩展
_BASE_EXTENSIONS = (
    "tables",
    "fenced_code",
    "footnotes",
    "attr_list",
    "def_list",
    "abbr",
    "md_in_html",
    "admonition",
    "sane_lists",
    "meta",
    "toc",
)

#: 受限后端无法表达的标签，因此不启用定义列表
_SIMPLE_EXTENSIONS = tuple(e for e in _BASE_EXTENSIONS if e != "def_list")

_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")', re.IGNORECASE)
_TASK_RE = re.compile(r"<li>\[([ xX])\]\s*")
_HR_RE = re.compile(r"<hr\s*/?>", re.IGNORECASE)
_BLOCKQUOTE_RE = re.compile(r"<blockquote>(.*?)</blockquote>", re.DOTALL | re.IGNORECASE)
_DEL_RE = re.compile(r"<del>(.*?)</del>", re.DOTALL | re.IGNORECASE)
_ADMONITION_RE = re.compile(r'<div class="admonition\b[^"]*">', re.IGNORECASE)
_ADMONITION_TITLE_RE = re.compile(
    r'<p class="admonition-title">(.*?)</p>', re.DOTALL | re.IGNORECASE
)
#: 行内代码（排除已被 Pygments 填充 span 的代码块）
_INLINE_CODE_RE = re.compile(r"<code>(?!<span)(.*?)</code>", re.DOTALL)
#: 标题与链接——受限后端不会继承颜色，必须逐个显式指定
#: （标题标签通常带有 toc 扩展生成的 id 属性，因此要保留原有属性）
_HEADING_RE = re.compile(r"<h([1-6])([^>]*)>", re.IGNORECASE)
_LINK_RE = re.compile(r"<a href=", re.IGNORECASE)

#: 受限后端下 blockquote 的引导符
_QUOTE_BAR = "│ "


class _StrikeThroughProcessor(InlineProcessor):
    """把 ``~~文本~~`` 转成 ``<del>``（Python-Markdown 默认不支持该 GFM 语法）。"""

    def handleMatch(self, m, data):  # noqa: N802 - 沿用上游命名
        element = etree.Element("del")
        element.text = m.group(1)
        return element, m.start(0), m.end(0)


class StrikeThroughExtension(Extension):
    """为 GFM 风格的删除线提供支持。"""

    def extendMarkdown(self, md) -> None:  # noqa: N802 - 沿用上游命名
        # 优先级 175：早于链接与强调，但晚于转义
        md.inlinePatterns.register(
            _StrikeThroughProcessor(r"~~(.+?)~~", md), "mdv_strikethrough", 175
        )


@dataclass
class RenderResult:
    """一次渲染的产物。"""

    html: str
    css: str
    toc_tokens: list[dict] = field(default_factory=list)
    meta: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_toc(self) -> bool:
        """是否存在可用于侧栏的目录。"""
        return bool(self.toc_tokens)


def create_markdown(
    profile: str = RICH,
    theme: Theme | None = None,
    inline_styles: bool | None = None,
) -> markdown.Markdown:
    """构造一个配置好扩展的 :class:`markdown.Markdown` 实例。

    复用同一个实例可以获得更好的性能（Pygments formatter 会被缓存），
    但每次 :meth:`~markdown.Markdown.convert` 前需要调用 :meth:`reset`。
    """
    simple = profile == SIMPLE
    if inline_styles is None:
        inline_styles = simple
    style = (theme.pygments_style if theme else "default") or "default"

    pre_style = ""
    if simple and theme:
        pre_style = f"background-color: {theme.code_bg}"

    extensions = list(_SIMPLE_EXTENSIONS if simple else _BASE_EXTENSIONS)
    extensions.append(StrikeThroughExtension())
    extensions.append(
        CodeHighlightExtension(
            style=style,
            inline_styles=inline_styles,
            guess_lang=True,
            pre_style=pre_style,
        )
    )
    return markdown.Markdown(
        extensions=extensions,
        extension_configs={"toc": {"permalink": False, "toc_depth": "1-6"}},
    )


def render(
    text: str,
    *,
    profile: str = RICH,
    theme: Theme | None = None,
    base_dir: Path | None = None,
    font_size: int = 14,
    md: markdown.Markdown | None = None,
) -> RenderResult:
    """把 Markdown 文本渲染为 HTML。

    :param text: Markdown 源文本
    :param profile: ``rich`` 或 ``simple``
    :param theme: 主题，用于代码块配色与内联样式
    :param base_dir: 文档所在目录，用于解析相对图片路径
    :param font_size: 正文字号（仅 rich 档位使用）
    :param md: 可复用的 Markdown 实例
    """
    converter = md or create_markdown(profile=profile, theme=theme)
    converter.reset()
    body = converter.convert(text)

    if profile == SIMPLE:
        body = _to_simple_html(body, theme, base_dir)
        css = ""
    else:
        body = _resolve_images(body, base_dir, as_uri=True)
        code_css = pygments_css(
            (theme.pygments_style if theme else "default") or "default"
        )
        css = build_css(theme, font_size, code_css) if theme else code_css

    meta = dict(getattr(converter, "Meta", {}) or {})
    return RenderResult(
        html=body,
        css=css,
        toc_tokens=list(getattr(converter, "toc_tokens", []) or []),
        meta=meta,
    )


# ---------------------------------------------------------------------- 降级处理
def _style_attr(theme: Theme | None, key: str) -> str:
    if theme is None:
        return ""
    entries = theme.inline.get(key) or {}
    if not entries:
        return ""
    return "; ".join(f"{k}: {v}" for k, v in entries.items())


def _wrap(key: str, theme: Theme | None) -> str:
    """生成 ``style="..."`` 片段；无样式时返回空字符串。"""
    style = _style_attr(theme, key)
    return f' style="{style}"' if style else ""


def _to_simple_html(
    body: str, theme: Theme | None, base_dir: Path | None
) -> str:
    """把标准 HTML 降级为受限后端可渲染的形式。"""
    # 引用块：tkhtmlview 不认识 blockquote，换成带样式的 div 并加引导符
    def blockquote_repl(match: re.Match[str]) -> str:
        inner = re.sub(r"<p>", f"<p>{_QUOTE_BAR}", match.group(1))
        return f"<div{_wrap('blockquote', theme)}>{inner}</div>"

    body = _BLOCKQUOTE_RE.sub(blockquote_repl, body)

    # 分隔线：用一行字符模拟
    hr_style = _wrap("hr", theme)
    body = _HR_RE.sub(f"<p{hr_style}>{'─' * 48}</p>", body)

    # 删除线：tkhtmlview 不认识 <del>，但支持 text-decoration
    del_open = f"<span{_wrap('del', theme)}>"
    body = _DEL_RE.sub(rf"{del_open}\1</span>", body)

    # 任务列表复选框
    body = _TASK_RE.sub(
        lambda m: "<li>☑ " if m.group(1).lower() == "x" else "<li>☐ ", body
    )

    # 提示块（admonition）：class 不生效，改为内联样式 + 加粗标题
    body = _ADMONITION_RE.sub(f"<div{_wrap('admonition', theme)}>", body)
    body = _ADMONITION_TITLE_RE.sub(r"<p><b>\1</b></p>", body)

    # 行内代码：受限后端下同样只能靠内联样式着色
    code_open = f"<code{_wrap('code', theme)}>"
    body = _INLINE_CODE_RE.sub(rf"{code_open}\1</code>", body)

    # 标题与链接：显式上色，否则深色主题下会变成黑底黑字
    heading_attr = _wrap("heading", theme)
    if heading_attr:
        body = _HEADING_RE.sub(rf"<h\1\2{heading_attr}>", body)
    link_attr = _wrap("link", theme)
    if link_attr:
        body = _LINK_RE.sub(rf"<a{link_attr} href=", body)

    return _resolve_images(body, base_dir, as_uri=False)


_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


def extract_headings(text: str, max_level: int = 6) -> list[dict]:
    """从 Markdown 原文提取 ATX 标题，用于后端不生成目录时兜底。

    会跳过围栏代码块内部的 ``#`` 行，避免把注释当成标题。
    """
    tokens: list[dict] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _ATX_HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        if level > max_level:
            continue
        name = match.group(2).strip()
        if not name:
            continue
        tokens.append(
            {
                "level": level,
                "id": _slugify(name),
                "name": name,
                "html": name,
                "children": [],
            }
        )
    return tokens


def _slugify(value: str) -> str:
    """与 Python-Markdown 的 slugify 大致一致的简化实现。"""
    value = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", value).strip().lower()
    return re.sub(r"[\s]+", "-", value)


def _resolve_images(body: str, base_dir: Path | None, *, as_uri: bool) -> str:
    """把相对图片路径转换为后端可直接加载的形式。

    * ``as_uri=True``  → ``file:///...``，供 tkinterweb / 浏览器使用；
    * ``as_uri=False`` → 本机绝对路径，供 tkhtmlview 使用（它用
      :func:`os.path.exists` 判断，不认 ``file://`` 协议）。
    """
    if base_dir is None:
        return body

    def repl(match: re.Match[str]) -> str:
        src = match.group(2).strip()
        if not src or re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#|data:)", src, re.I):
            return match.group(0)
        try:
            target = (base_dir / src).resolve()
        except (OSError, ValueError):
            return match.group(0)
        if not target.is_file():
            return match.group(0)
        new_src = target.as_uri() if as_uri else str(target)
        return f"{match.group(1)}{new_src}{match.group(3)}"

    return _IMG_SRC_RE.sub(repl, body)

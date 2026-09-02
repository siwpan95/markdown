r"""基于 Pygments 的代码块高亮扩展。

为什么需要自己写：

``codehilite`` 只处理缩进代码块和 ``:::lang`` 形式的围栏块，而绝大多数 Markdown
使用 ```lang 围栏。负责围栏的 ``fenced_code`` 扩展只输出
``<pre><code class="language-python">``，不会调用 Pygments，于是代码高亮形同虚设。

这里提供 :class:`CodeHighlightExtension`，作为一个 ``Postprocessor`` 在最终 HTML
上工作——此时所有代码块占位符都已被还原，可以安全地重新渲染。

两种输出模式：

* ``inline_styles=True``  —— 输出 ``<span style="color: #xxx">``，供只识别内联
  样式的 tkhtmlview 使用；
* ``inline_styles=False`` —— 输出 Pygments 的 class，配合 :func:`pygments_css`
  生成的样式表使用（tkinterweb 后端、导出的 HTML）。
"""

from __future__ import annotations

import html
import re
from typing import Any

from markdown import Extension
from markdown.postprocessors import Postprocessor
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import (
    TextLexer,
    get_lexer_by_name,
    guess_lexer,
)
from pygments.util import ClassNotFound

__all__ = ["CodeHighlightExtension", "pygments_css"]

#: 匹配 fenced_code / codehilite 生成的代码块
_BLOCK_RE = re.compile(
    r"<pre(?P<pre_attrs>[^>]*)>\s*<code(?P<code_attrs>[^>]*)>(?P<code>.*?)</code>\s*</pre>",
    re.DOTALL,
)

#: 从 class 属性中提取语言：language-python / lang-python / highlight-python
_CLASS_RE = re.compile(r"class=[\"']?(?:language-|lang-|highlight-)?([\w+#.\-]+)")


class CodeHighlightPostprocessor(Postprocessor):
    """把 ``<pre><code>`` 块替换为 Pygments 高亮结果。"""

    def __init__(
        self,
        md,
        style: str = "default",
        inline_styles: bool = True,
        guess_lang: bool = True,
        pre_style: str = "",
        max_chars: int = 200_000,
    ) -> None:
        super().__init__(md)
        self.style = style
        self.inline_styles = inline_styles
        self.guess_lang = guess_lang
        self.pre_style = pre_style
        self.max_chars = max_chars
        self._formatters: dict[tuple[str, bool], HtmlFormatter] = {}

    # ------------------------------------------------------------------ 工具
    def _formatter(self) -> HtmlFormatter:
        key = (self.style, self.inline_styles)
        if key not in self._formatters:
            self._formatters[key] = HtmlFormatter(
                nowrap=True,
                noclasses=self.inline_styles,
                style=self.style,
                cssclass="codehilite",
            )
        return self._formatters[key]

    def _lexer(self, lang: str, code: str):
        """按语言名取 lexer，失败时猜测或退化为纯文本。"""
        if lang:
            for name in (lang, lang.lower()):
                try:
                    return get_lexer_by_name(name, stripnl=False)
                except ClassNotFound:
                    continue
        if self.guess_lang:
            try:
                return guess_lexer(code)
            except ClassNotFound:
                pass
        return TextLexer(stripnl=False)

    # ------------------------------------------------------------------ 主流程
    def run(self, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            raw = html.unescape(match.group("code"))
            if len(raw) > self.max_chars:
                # 过大的代码块跳过着色，避免界面长时间卡顿
                return match.group(0)
            class_attr = match.group("code_attrs")
            lang_match = _CLASS_RE.search(class_attr)
            lang = lang_match.group(1) if lang_match else ""
            if lang in ("text", "plain", "none"):
                return match.group(0)

            try:
                inner = highlight(raw, self._lexer(lang, raw), self._formatter())
            except Exception:  # noqa: BLE001 - 高亮失败不应影响整篇渲染
                return match.group(0)

            pre_style = f' style="{self.pre_style}"' if self.pre_style else ""
            return f"<pre{pre_style}><code>{inner}</code></pre>"

        return _BLOCK_RE.sub(replace, text)


class CodeHighlightExtension(Extension):
    """Markdown 扩展入口，见模块文档字符串。"""

    def __init__(self, **kwargs: Any) -> None:
        self.config = {
            "style": ["default", "Pygments 配色方案名 - 默认: default"],
            "inline_styles": [True, "使用内联样式而非 CSS class - 默认: True"],
            "guess_lang": [True, "未标注语言时自动猜测 - 默认: True"],
            "pre_style": ["", "代码块 <pre> 的内联样式 - 默认: 空"],
            "max_chars": [200_000, "超过该长度的代码块跳过着色 - 默认: 200000"],
        }
        super().__init__(**kwargs)

    def extendMarkdown(self, md) -> None:  # noqa: N802 - 沿用上游命名
        opts = {
            key: self.getConfig(key)
            for key in ("style", "inline_styles", "guess_lang", "pre_style", "max_chars")
        }
        # 优先级低于 raw_html(30) 与 amp_substitute(20)，确保拿到最终文本
        md.postprocessors.register(
            CodeHighlightPostprocessor(md, **opts), "mdv_highlight", 5
        )


def pygments_css(style: str = "default", css_class: str = "codehilite") -> str:
    """生成 Pygments 的 CSS class 定义，供完整 HTML 渲染与导出使用。"""
    try:
        return HtmlFormatter(style=style, cssclass=css_class).get_style_defs()
    except ClassNotFound:
        return HtmlFormatter(style="default", cssclass=css_class).get_style_defs()

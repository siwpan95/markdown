"""渲染服务 —— ``ctx.renderer``。

对 :mod:`mdviewer.core.renderer` 做一层薄封装，只多两件事：

* 按 ``profile`` 缓存 :class:`markdown.Markdown` 实例（Pygments formatter 构造
  开销不小，每次渲染都重建会让大文档明显卡顿）；
* 主题或代码块样式变化后自动丢弃缓存。

渲染结果本身不含任何 Tk 依赖，因此 CLI 的无界面转换也走这个服务。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import markdown

from cordis import Service

from .. import events
from ..core.renderer import RICH, SIMPLE, RenderResult, create_markdown, extract_headings, render
from ..core.theme import Theme

if TYPE_CHECKING:  # pragma: no cover
    from cordis import Context


class RenderService(Service):
    """Markdown → HTML。"""

    name = "renderer"

    def __init__(self, ctx: "Context", config: Any = None) -> None:
        super().__init__(ctx, config)
        self._cache: dict[tuple[str, str], markdown.Markdown] = {}

        # 主题换了要重建实例：Pygments 的 style 在构造时就固定了
        ctx.on(events.THEME_CHANGE, lambda theme: self.invalidate())

    # ------------------------------------------------------------------ 缓存
    def converter(self, profile: str, theme: Theme) -> markdown.Markdown:
        key = (profile, theme.pygments_style)
        converter = self._cache.get(key)
        if converter is None:
            converter = create_markdown(profile=profile, theme=theme)
            self._cache[key] = converter
        return converter

    def invalidate(self) -> None:
        """丢弃缓存的 Markdown 实例。"""
        self._cache.clear()

    # ------------------------------------------------------------------ 渲染
    def render_text(
        self,
        text: str,
        *,
        profile: str = RICH,
        theme: Theme | None = None,
        base_dir: Path | None = None,
        font_size: int = 14,
    ) -> RenderResult:
        if theme is None and self.ctx.get("themes") is not None:
            theme = self.ctx.themes.current
        return render(
            text,
            profile=profile,
            theme=theme,
            base_dir=base_dir,
            font_size=font_size,
            md=self.converter(profile, theme) if theme else None,
        )

    def render_source(self, text: str) -> RenderResult:
        """纯文本档位：直接展示 Markdown 源码，目录从源码里提取。"""
        return RenderResult(html=text, css="", toc_tokens=extract_headings(text))

    @property
    def profiles(self) -> tuple[str, str]:
        return (RICH, SIMPLE)


__all__ = ["RenderService"]

"""主题服务 —— ``ctx.themes``。

只管“当前是哪套配色、字号多少”，不碰任何 Tk 控件：把配色应用到 ttk 控件上
是 :mod:`mdviewer.plugins.appearance` 的事。这样主题服务可以在无界面环境下
单独测试，也能被 CLI 的 ``--theme`` 直接复用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cordis import Service

from .. import events
from ..core.theme import THEMES, Theme, get_theme

if TYPE_CHECKING:  # pragma: no cover
    from cordis import Context

DEFAULT_FONT_SIZE = 14


class ThemeService(Service):
    """当前主题与正文字号。"""

    name = "themes"
    inject = ["settings"]

    def __init__(self, ctx: "Context", config: Any = None) -> None:
        super().__init__(ctx, config)
        self.current: Theme = get_theme(self.ctx.settings.get("theme"))
        self._font_size = int(self.ctx.settings.get("base_font_size", DEFAULT_FONT_SIZE))

        # 设置被外部改写（例如别的插件直接改了 settings）时同步过来
        ctx.on(events.SETTINGS_CHANGE, self._on_settings_change)

    # ------------------------------------------------------------------ 读取
    @property
    def key(self) -> str:
        return self.current.key

    @property
    def label(self) -> str:
        return self.current.label

    @property
    def font_size(self) -> int:
        return self._font_size

    @staticmethod
    def available() -> tuple[Theme, ...]:
        return tuple(THEMES.values())

    # ------------------------------------------------------------------ 修改
    def set_theme(self, key: str) -> Theme:
        """切换到指定主题；与当前一致时不做任何事。"""
        theme = get_theme(key)
        if theme.key == self.current.key:
            return self.current
        self.current = theme
        self.ctx.settings.update(theme=theme.key)
        self.ctx.emit(events.THEME_CHANGE, theme)
        return theme

    def toggle(self) -> Theme:
        """在浅色/深色之间切换。"""
        return self.set_theme("dark" if self.current.key == "light" else "light")

    def set_font_size(self, size: int) -> int:
        """设置正文字号；0 表示重置为默认值。"""
        target = DEFAULT_FONT_SIZE if size == 0 else size
        target = self.ctx.settings.clamp_font_size(target)
        if target == self._font_size:
            return target
        self._font_size = target
        self.ctx.settings.update(base_font_size=target)
        self.ctx.emit(events.FONT_SIZE_CHANGE, target)
        return target

    def zoom(self, delta: int) -> int:
        return self.set_font_size(0 if delta == 0 else self._font_size + delta)

    # ------------------------------------------------------------------ 联动
    def _on_settings_change(self, key: str, value: Any) -> None:
        if key == "theme" and value != self.current.key:
            self.current = get_theme(value)
            self.ctx.emit(events.THEME_CHANGE, self.current)
        elif key == "base_font_size" and int(value) != self._font_size:
            self._font_size = int(value)
            self.ctx.emit(events.FONT_SIZE_CHANGE, self._font_size)


__all__ = ["DEFAULT_FONT_SIZE", "ThemeService"]

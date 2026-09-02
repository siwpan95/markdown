"""设置服务 —— ``ctx.settings``。

把原来散落在 ``MarkdownViewerApp`` 里的 ``self.settings.xxx = ...; self.settings.save()``
收敛成一个带变更广播的服务：

* 写入一律走 :meth:`SettingsService.update`，它会逐项比对、只在真正变化时发
  ``settings/change``；
* 持久化由服务负责，调用方不再关心 ``save()`` 什么时候调。

这样“自动换行”开关、`Ctrl+=` 字号、目录显隐等设置项的联动，插件之间不需要
互相认识，各自订阅 ``settings/change`` 即可。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cordis import Service

from .. import events
from ..core.config import Settings

if TYPE_CHECKING:  # pragma: no cover
    from cordis import Context

#: 允许通过 ``update()`` 修改的字段（其余视为内部状态）
PERSISTED_FIELDS = (
    "theme",
    "backend",
    "base_font_size",
    "show_toc",
    "auto_reload",
    "word_wrap",
    "window_geometry",
    "recent_files",
)


class SettingsService(Service):
    """用户偏好的读写与持久化。"""

    name = "settings"

    def __init__(self, ctx: "Context", config: Any = None) -> None:
        super().__init__(ctx, config)
        self.data = Settings.load()
        #: 覆盖默认值的启动参数（命令行优先级高于磁盘上的设置）
        self.overrides: dict[str, Any] = {}
        if isinstance(self.config, dict):
            self.overrides = {
                k: v for k, v in self.config.items() if v is not None
            }
            for key, value in self.overrides.items():
                if key in PERSISTED_FIELDS:
                    setattr(self.data, key, value)

    # ------------------------------------------------------------------ 读取
    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self.data, key, default)

    def __getattr__(self, key: str) -> Any:
        """允许 ``ctx.settings.theme`` 这样的直接访问。"""
        data = self.__dict__.get("data")
        if data is not None and hasattr(data, key):
            return getattr(data, key)
        raise AttributeError(key)

    # ------------------------------------------------------------------ 写入
    def update(self, **changes: Any) -> dict[str, Any]:
        """批量更新设置；返回真正发生变化的字段。"""
        applied: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in PERSISTED_FIELDS:
                raise KeyError(f"未知的设置项：{key}")
            if getattr(self.data, key) == value:
                continue
            setattr(self.data, key, value)
            applied[key] = value
        if applied:
            self.save()
            for key, value in applied.items():
                self.ctx.emit(events.SETTINGS_CHANGE, key, value)
        return applied

    def save(self) -> None:
        self.data.save()

    # ------------------------------------------------------------------ 派生
    @property
    def font_size(self) -> int:
        return int(self.data.base_font_size)

    def clamp_font_size(self, size: int) -> int:
        return max(Settings._MIN_FONT_SIZE, min(Settings._MAX_FONT_SIZE, size))


__all__ = ["PERSISTED_FIELDS", "SettingsService"]

"""后端注册服务 —— ``ctx.backends``。

原来 :mod:`mdviewer.backends` 里的 ``create_backend`` 是一个硬编码三选一的工厂：
想加一个后端就得改那个 ``if/elif``。这里改成注册表——

* 后端由插件注册（见 :mod:`mdviewer.plugins.backend_tkhtmlview` 等）；
* 每个后端带一个 ``priority``，创建时按优先级探测，第一个能构造出来的胜出；
* 探测失败的原因被记录下来，供状态栏显示“为什么降级”。

服务本身只依赖 ``settings`` / ``themes`` / ``window``，不 import 任何具体后端。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from cordis import Service

from .. import events

if TYPE_CHECKING:  # pragma: no cover
    from ..backends.base import Backend


@dataclass(order=False)
class BackendSpec:
    """一个已注册的渲染后端。"""

    key: str
    label: str
    factory: Callable[..., "Backend"]
    #: 数字越小优先级越高
    priority: int = 100
    #: 是否支持完整 CSS 样式表
    supports_css: bool = False
    #: 菜单里显示的简称；留空则用 :attr:`label`
    menu_label: str = ""
    probe: Callable[[], None] | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def short(self) -> str:
        return self.menu_label or self.label


class BackendService(Service):
    """渲染后端的注册表与当前实例。"""

    name = "backends"
    inject = ["settings", "themes", "window"]

    def __init__(self, ctx: "Context", config: Any = None) -> None:  # noqa: F821
        super().__init__(ctx, config)
        self._specs: dict[str, BackendSpec] = {}
        self.current: "Backend | None" = None
        self.note: str = ""

    # ------------------------------------------------------------------ 注册
    def register(
        self,
        key: str,
        label: str,
        factory: Callable[..., "Backend"],
        *,
        priority: int = 100,
        supports_css: bool = False,
        menu_label: str = "",
        probe: Callable[[], None] | None = None,
    ) -> Callable[[], None]:
        """注册一个后端，返回撤销函数（插件卸载时自动调用）。"""
        spec = BackendSpec(
            key=key,
            label=label,
            factory=factory,
            priority=priority,
            supports_css=supports_css,
            menu_label=menu_label,
            probe=probe,
        )
        self._specs[key] = spec
        return lambda: self._specs.pop(key, None)

    def unregister(self, key: str) -> None:
        self._specs.pop(key, None)

    # ------------------------------------------------------------------ 查询
    def spec(self, key: str) -> BackendSpec | None:
        return self._specs.get(key)

    def specs(self) -> list[BackendSpec]:
        """按优先级排序的后端列表。"""
        return sorted(self._specs.values(), key=lambda s: (s.priority, s.key))

    def keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.specs())

    def choices(self) -> tuple[str, ...]:
        """设置项 ``backend`` 的合法取值。"""
        return ("auto",) + self.keys()

    def label(self, key: str) -> str:
        """菜单/命令行用的简称。"""
        if key == "auto":
            return "自动"
        spec = self._specs.get(key)
        return spec.short if spec else key

    def profile_for(self, backend: "Backend | None" = None) -> str:
        """该后端对应的渲染档位。"""
        from ..core.renderer import RICH, SIMPLE

        backend = backend or self.current
        if backend is None:
            return SIMPLE
        return RICH if backend.supports_css else SIMPLE

    @property
    def status_text(self) -> str:
        if self.current is None:
            return ""
        text = self.current.label
        if self.note:
            text = f"{text}（{self.note}）"
        return text

    # ------------------------------------------------------------------ 探测
    def probe_all(self) -> list[tuple["BackendSpec", bool, BaseException | None]]:
        """逐个尝试构造所有已注册后端，供 ``--list-backends`` 生成环境报告。"""
        results: list[tuple[BackendSpec, bool, BaseException | None]] = []
        for spec in self.specs():
            try:
                if spec.probe is not None:
                    spec.probe()
                backend = spec.factory(
                    self.ctx, self.ctx.themes.current, self.ctx.themes.font_size
                )
            except Exception as error:  # noqa: BLE001
                results.append((spec, False, error))
            else:
                backend.destroy()
                results.append((spec, True, None))
        return results

    # ------------------------------------------------------------------ 创建
    def create(self, preference: str | None = None) -> "Backend":
        """按优先级探测并创建后端；全部失败时抛出最后一个异常。"""
        settings = self.ctx.settings
        key = preference or settings.get("backend", "auto")
        ordered = [spec.key for spec in self.specs()]
        if key in self._specs:
            ordered = [key] + [k for k in ordered if k != key]

        notes: list[str] = []
        last_error: BaseException | None = None
        for name in ordered:
            spec = self._specs[name]
            try:
                if spec.probe is not None:
                    spec.probe()
                backend = spec.factory(
                    self.ctx,
                    self.ctx.themes.current,
                    self.ctx.themes.font_size,
                )
            except Exception as error:  # noqa: BLE001 - 任何原因都视为不可用
                notes.append(f"{spec.short} 不可用（{type(error).__name__}）")
                last_error = error
                continue
            self.note = "；".join(notes) if notes and name != ordered[0] else ""
            return backend

        raise RuntimeError(
            "没有可用的渲染后端：" + "；".join(notes)
        ) from last_error

    def attach(self, backend: "Backend") -> None:
        """把后端挂到内容区并广播切换事件。"""
        master = self.ctx.window.content
        backend.widget.pack(fill="both", expand=True)
        self.current = backend
        if hasattr(backend, "set_word_wrap"):
            backend.set_word_wrap(bool(self.ctx.settings.get("word_wrap", True)))
        self.ctx.emit(events.BACKEND_CHANGE, backend)

    def destroy(self) -> None:
        if self.current is not None:
            try:
                self.current.destroy()
            except Exception:  # noqa: BLE001 - 销毁失败不应阻断切换
                pass
            self.current = None

    def switch(self, key: str) -> "Backend":
        """切换后端：先销毁旧的，再创建新的。"""
        self.destroy()
        self.ctx.settings.update(backend=key)
        backend = self.create(key)
        self.attach(backend)
        return backend


__all__ = ["BackendService", "BackendSpec"]

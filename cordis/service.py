"""服务基类。

对应 TypeScript 版的 ``packages/core/src/service.ts``。

服务就是占据一个稳定上下文键的对象（``ctx.settings``、``ctx.documents`` …）。
继承 :class:`Service` 的类可以直接当作插件加载::

    class SettingsService(Service):
        name = "settings"

        def __init__(self, ctx, config=None):
            super().__init__(ctx, config)
            self.data = Settings.load()

    ctx.plugin(SettingsService)   # 之后 ctx.settings 即可用

服务卸载时，它占据的上下文键会自动释放，所有通过 ``inject`` 声明依赖它的插件
会被自动停用 —— 这是 Cordis “空间可组合性”的核心保证。
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Callable

from .registry import InjectSpec
from .utils import CordisError

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context


class Service:
    """所有服务的基类。"""

    #: 服务名（必须提供，或通过 ``provide`` / 构造参数给出）
    name: str | None = None
    #: 依赖声明，写法同插件的 ``inject``
    inject: InjectSpec | None = None
    #: 对外提供的上下文键；可以是多个别名
    provide: str | list[str] | None = None

    def __init__(
        self,
        ctx: "Context",
        config: Any = None,
        *,
        name: str | None = None,
        check: Callable[[Any], bool] | None = None,
    ) -> None:
        # 兼容 Cordis 的 ``super(ctx, 'foo')`` 写法：字符串参数视为服务名
        if isinstance(config, str):
            name = name or config
            config = None

        self.ctx = ctx
        self.config: Any = config if config is not None else {}

        declared = name or self.name or self.provide
        if isinstance(declared, (list, tuple)):
            aliases = list(declared)
        elif declared:
            aliases = [declared]
        else:
            raise CordisError(
                "MISSING_SERVICE_NAME",
                f"{type(self).__name__} 必须声明 name 或 provide",
            )

        self.name = aliases[0]
        for alias in aliases:
            ctx.provide(alias, self, check)

    # ------------------------------------------------------------------ 生命周期
    def init(self) -> Any:
        """可选的初始化钩子。

        在构造函数之后由 Fiber 调用；返回值可以是 disposer（同 ``ctx.effect``）。
        需要“注册事件后才算就绪”的服务可以把等待逻辑放在这里。
        """
        return None

    def fork(self, **props: Any) -> "Service":
        """派生一个覆盖部分属性的副本（对应上游的 ``Service.extend``）。"""
        clone = copy.copy(self)
        for key, value in props.items():
            object.__setattr__(clone, key, value)
        return clone

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<{type(self).__name__} {self.name}>"


__all__ = ["Service"]

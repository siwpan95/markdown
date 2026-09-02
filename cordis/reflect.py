"""服务注册与依赖解析。

对应 TypeScript 版的 ``packages/core/src/reflect.ts``。

上游用 ``Proxy`` 拦截 ``ctx.foo`` 的读写，Python 没有 Proxy，改由
:class:`~cordis.context.Context` 的 ``__getattr__`` / ``__setattr__`` 调用本模块
的 :meth:`ReflectService.resolve` / :meth:`ReflectService.assign`，语义保持一致：

* 读一个**已 provide 但当前不可用**的服务 → 抛 ``CordisError``；
* 在插件里读一个**没有写进 inject** 的服务 → 抛 ``CordisError``；
* 在插件里写一个**没有 provide** 的属性 → 抛 ``CordisError``。

这三条是“空间可组合性”的运行时保证：依赖关系必须显式声明，否则立刻失败。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from .fiber import FiberState
from .utils import CordisError, Symbol, symbols

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context
    from .fiber import Fiber


@dataclass
class Impl:
    """一个已注册的服务实例。"""

    name: str
    fiber: "Fiber"
    value: Any = None
    check: Callable[[Any], bool] | None = None


@dataclass
class Property:
    """上下文中某个属性名的声明（服务或访问器）。"""

    type: str  # 'service' | 'accessor'
    get: Callable[..., Any] | None = None
    set: Callable[..., bool] | None = None


class ReflectService:
    """``ctx.reflect`` —— 服务表与访问器表。"""

    def __init__(self, ctx: "Context") -> None:
        self.ctx = ctx
        self.store: dict[Any, Impl] = {}
        self.props: dict[str, Property] = {}

        # 上游在这里用 mixin 把 ctx.on / ctx.plugin 等提升为访问器（靠 JS 的 this
        # 绑定把调用上下文带过来）。Python 版改成 Context 上的真方法显式传 ctx，
        # 见 cordis/context.py 的模块注释。mixin 本身保留，供需要时手工调用。

    # ------------------------------------------------------------------ 查询
    def get(self, name: str, strict: bool = True, ctx: "Context | None" = None) -> Any:
        """按名字取服务值；不可用（或未注册）时返回 ``None``。"""
        impl = self._get_impl(name, strict, ctx)
        return impl.value if impl is not None else None

    def _get_impl(
        self, name: str, strict: bool = True, ctx: "Context | None" = None
    ) -> Impl | None:
        ctx = ctx or self.ctx
        key = ctx._isolate.get(name)
        if key is None:
            return None
        impl = self.store.get(key)
        if impl is None:
            return None
        if strict and impl.fiber.state != FiberState.ACTIVE:
            return None
        return impl

    def has(self, name: str, ctx: "Context | None" = None) -> bool:
        return self._get_impl(name, strict=False, ctx=ctx) is not None

    def set(self, name: str, value: Any, ctx: "Context | None" = None) -> bool:
        """给已注册的服务槽位赋值。"""
        ctx = ctx or self.ctx
        impl = self._get_impl(name, strict=False, ctx=ctx)
        if impl is None:
            raise CordisError(
                "UNPROVIDED_PROPERTY", f'cannot set property "{name}" without provide'
            )
        if impl.fiber is not ctx.fiber:
            raise CordisError(
                "MULTI_FIBER_PROPERTY",
                f'cannot set property "{name}" in multiple fibers',
            )
        impl.value = value
        return True

    # ------------------------------------------------------------------ 注册
    def provide(
        self,
        name: str,
        value: Any = None,
        check: Callable[[Any], bool] | None = None,
        ctx: "Context | None" = None,
    ) -> Callable[[], Any]:
        """注册一个服务，返回撤销函数（Fiber 卸载时会自动调用）。"""
        ctx = ctx or self.ctx

        def body() -> Callable[[], Any]:
            existing = self.props.get(name)
            if existing is None:
                self.props[name] = Property(type="service")
            elif existing.type != "service":
                raise CordisError(
                    "DUPLICATE_PROPERTY",
                    f'property "{name}" is already declared as {existing.type}',
                )

            root_isolate = ctx.root._isolate
            if root_isolate.get(name) is None:
                root_isolate[name] = Symbol(name)
            key = ctx._isolate.get(name)
            if key in self.store:
                raise CordisError(
                    "DUPLICATE_SERVICE",
                    f'service "{name}" has been registered at '
                    f"<{self.store[key].fiber.name}>",
                )

            impl = Impl(name=name, value=value, fiber=ctx.fiber, check=check)
            self.store[key] = impl
            if ctx.fiber.store is not None:
                ctx.fiber.store[name] = impl
            if ctx.fiber.state == FiberState.ACTIVE:
                self.notify([name])

            def dispose() -> None:
                self.store.pop(key, None)
                self.notify([name])
                if ctx.fiber.store is not None:
                    ctx.fiber.store.pop(name, None)

            return dispose

        return ctx.fiber.effect(body, f"ctx.provide({name!r})")

    def accessor(
        self,
        name: str,
        get: Callable[..., Any],
        set_: Callable[..., bool] | None = None,
        ctx: "Context | None" = None,
    ) -> Callable[[], Any]:
        """注册一个计算属性。"""
        ctx = ctx or self.ctx

        def body() -> Callable[[], None]:
            if name in self.props:
                raise CordisError(
                    "DUPLICATE_PROPERTY",
                    f'property "{name}" is already declared as '
                    f"{self.props[name].type}",
                )
            self.props[name] = Property(type="accessor", get=get, set=set_)
            return lambda: self.props.pop(name, None)

        return ctx.fiber.effect(body, f"ctx.accessor({name!r})")

    def mixin(
        self,
        source: str,
        mixins: list[str] | dict[str, str],
        ctx: "Context | None" = None,
    ) -> Callable[[], Any]:
        """把 ``ctx.<source>`` 的一批方法提升到 ``ctx`` 上。"""
        ctx = ctx or self.ctx

        def make_getter(key: str) -> Callable[[], Any]:
            def getter(accessor_ctx: "Context") -> Any:
                service = getattr(accessor_ctx, source)
                if service is None:
                    return None
                return getattr(service, key)

            return getter

        def body():
            entries = (
                [(key, key) for key in mixins]
                if isinstance(mixins, (list, tuple))
                else list(mixins.items())
            )
            for target, source_key in entries:
                yield self.accessor(target, make_getter(source_key), ctx=ctx)

        return ctx.fiber.effect(body, f"ctx.mixin({source!r})")

    # ------------------------------------------------------------------ 通知
    def notify(
        self,
        names: list[str],
        filter_: Callable[["Context", str], bool] | None = None,
    ) -> list["Fiber"]:
        """服务发生变化，重算所有依赖它的 Fiber。"""
        if filter_ is None:
            own = self.ctx._isolate

            def filter_(ctx: "Context", name: str) -> bool:
                return ctx._isolate.get(name) == own.get(name)

        fibers: list[Fiber] = []
        for runtime in list(self.ctx.registry.values()):
            for fiber in list(runtime.fibers):
                has_update = False
                for name in names:
                    if name not in fiber.inject:
                        continue
                    if not filter_(fiber.ctx, name):
                        continue
                    has_update = True
                    fiber._check_impl(name)
                if not has_update:
                    continue
                fiber._refresh()
                fibers.append(fiber)

        for name in names:
            shadow = self.ctx.extend({symbols.filter: lambda target, n=name: filter_(target, n)})
            impl = self._get_impl(name, strict=False)
            self.ctx.events.emit(
                shadow, "internal/service", name, impl.value if impl else None
            )
        return fibers

    # ------------------------------------------------------------------ 解析
    def resolve(self, ctx: "Context", name: str) -> Any:
        """解析 ``ctx.<name>``（服务或访问器）。"""
        error = CordisError(
            "UNINJECTED_PROPERTY", f'cannot get property "{name}" without inject'
        )
        prop = self.props.get(name)
        if prop is not None and prop.type == "accessor":
            assert prop.get is not None
            return prop.get(ctx)

        if ctx.fiber.runtime is None:
            return self.get(name, strict=False, ctx=ctx)

        key = ctx._isolate.get(name)
        fiber = ctx.fiber
        seen: set[int] = set()
        while True:
            if id(fiber) in seen:  # 理论上不可达，防御性保护
                raise error
            seen.add(id(fiber))
            impl = (fiber.store or {}).get(name)
            if impl is not None:
                return impl.value
            if name in fiber.inject:
                raise CordisError(
                    "INACTIVE_DEPENDENCY",
                    f'cannot get required service "{name}" in inactive context',
                )
            if fiber.runtime is None:
                raise error
            if fiber.parent._isolate.get(name) != key:
                raise error
            fiber = fiber.parent.fiber

    def assign(self, ctx: "Context", name: str, value: Any) -> bool:
        """处理 ``ctx.<name> = value``。"""
        prop = self.props.get(name)
        if prop is None:
            if ctx.fiber.runtime is None:
                ctx._own[name] = value
                return True
            raise CordisError(
                "UNPROVIDED_PROPERTY", f'cannot set property "{name}" without provide'
            )
        if prop.type == "accessor":
            if prop.set is None:
                raise CordisError(
                    "READONLY_PROPERTY", f'property "{name}" is readonly'
                )
            return prop.set(value)
        return ctx.reflect.set(name, value)


__all__ = ["Impl", "Property", "ReflectService"]

"""上下文容器。

对应 TypeScript 版的 ``packages/core/src/context.ts``。

:class:`Context` 是服务的容器，也是插件的作用域。它通过 ``extend`` 形成原型链
（子上下文只记录差异），因此每个插件拿到的 ``ctx`` 都是一个“视图”：共享同一份
服务表，但拥有独立的 Fiber、isolate 与 intercept。

与上游的差异（共三处，均为语言机制所迫）：

1. **没有 ``Proxy``，改用 ``__getattr__`` / ``__setattr__``。** 未声明的属性读写
   会被转发给 :class:`~cordis.reflect.ReflectService`，未注入即报错的语义不变。
2. **``ctx.on`` / ``ctx.plugin`` 等写成真方法**，而不是上游的 mixin 访问器。
   JavaScript 靠 ``this`` 绑定把调用上下文传给服务，Python 没有对应机制，
   这里显式传递，行为一致但更快也更易读。
3. **没有 ``shadow`` 追踪。** 上游用它做调用者敏感的服务分派，本项目没有
   多租户隔离需求，暂不移植（``isolate`` 已能覆盖隔离场景）。
"""

from __future__ import annotations

from typing import Any, Callable

from .events import EventsService
from .fiber import Fiber
from .logger import LoggerService
from .reflect import ReflectService
from .registry import InjectSpec, RegistryService
from .utils import ChainDict, Symbol, build_outer_stack, symbols


class Context:
    """服务容器与插件作用域。"""

    #: 事件分发用的标记：``ctx.emit(ctx, 'name', ...)`` 时它是 thisArg
    __cordis_scope__ = True

    def __init__(self, meta: dict | None = None, parent: "Context | None" = None) -> None:
        object.__setattr__(self, "_own", dict(meta or {}))
        object.__setattr__(self, "_parent", parent)
        if parent is None:
            self._bootstrap()

    # ------------------------------------------------------------------ 启动
    def _bootstrap(self) -> None:
        own = self._own
        own[symbols.isolate] = ChainDict()
        own[symbols.intercept] = ChainDict()
        #: 相对路径解析的基准目录（loader 用）；无 loader 时为项目根目录
        own["base_url"] = None
        own["root"] = self
        own["fiber"] = Fiber(self, None, {}, None, build_outer_stack)
        own["reflect"] = ReflectService(self)
        own["registry"] = RegistryService(self)
        own["events"] = EventsService(self)
        own["logger"] = LoggerService(self)
        # 启动期注册的 mixin 属于容器自身，不随任何 Fiber 卸载
        own["fiber"]._disposables.clear()

    # ------------------------------------------------------------------ 原型链
    def _lookup_own(self, name: str) -> Any:
        ctx: Context | None = self
        while ctx is not None:
            own = object.__getattribute__(ctx, "_own")
            if name in own:
                return own[name]
            ctx = object.__getattribute__(ctx, "_parent")
        raise KeyError(name)

    def __getattr__(self, name: str) -> Any:
        if not isinstance(name, str) or name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._lookup_own(name)
        except KeyError:
            pass
        return self._lookup_own("reflect").resolve(self, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if not isinstance(name, str) or name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        self._lookup_own("reflect").assign(self, name, value)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<Context {self.fiber.name}>"

    # ------------------------------------------------------------------ 派生态
    def extend(self, meta: dict | None = None) -> "Context":
        """派生一个子上下文；``meta`` 里的键会覆盖原型链上的同名属性。"""
        return Context(meta, self)

    def isolate(self, name: str, label: Symbol | None = None) -> "Context":
        """为某个服务名创建隔离域，域内外的插件互相看不见该服务。"""
        shadow = self._isolate.extend({name: label or Symbol(name)})
        return self.extend({symbols.isolate: shadow})

    def intercept(self, name: str, config: Any) -> "Context":
        """覆写某个服务在当前作用域内的配置。"""
        return self.extend({symbols.intercept: self._intercept.extend({name: config})})

    @property
    def _isolate(self) -> ChainDict:
        return self._lookup_own(symbols.isolate)

    @property
    def _intercept(self) -> ChainDict:
        return self._lookup_own(symbols.intercept)

    @staticmethod
    def is_context(value: Any) -> bool:
        return isinstance(value, Context)

    # ------------------------------------------------------------------ 服务
    def get(self, name: str, strict: bool = True) -> Any:
        return self.reflect.get(name, strict, self)

    def set(self, name: str, value: Any) -> bool:
        return self.reflect.set(name, value, self)

    def provide(
        self,
        name: str,
        value: Any = None,
        check: Callable[[Any], bool] | None = None,
    ) -> Callable[[], Any]:
        return self.reflect.provide(name, value, check, self)

    def accessor(
        self, name: str, get: Callable[..., Any], set_: Callable[..., bool] | None = None
    ) -> Callable[[], Any]:
        return self.reflect.accessor(name, get, set_, self)

    # ------------------------------------------------------------------ 插件
    def plugin(
        self,
        plugin: Any,
        config: Any = None,
        get_outer_stack: Callable[[], list[str]] | None = None,
    ) -> Fiber:
        return self.registry.plugin(plugin, config, self, get_outer_stack)

    def inject(self, deps: InjectSpec, callback: Callable[..., Any]) -> Fiber:
        return self.registry.inject(deps, callback, self)

    # ------------------------------------------------------------------ 事件
    def on(
        self,
        name: str,
        listener: Callable[..., Any],
        *,
        prepend: bool = False,
        global_: bool = False,
    ) -> Callable[[], bool]:
        return self.events.on(
            name, listener, self, prepend=prepend, global_=global_
        )

    def once(
        self,
        name: str,
        listener: Callable[..., Any],
        *,
        prepend: bool = False,
        global_: bool = False,
    ) -> Callable[[], bool]:
        return self.events.once(
            name, listener, self, prepend=prepend, global_=global_
        )

    def emit(self, *args: Any) -> None:
        self.events.emit(*args)

    def parallel(self, *args: Any) -> None:
        self.events.parallel(*args)

    def serial(self, *args: Any) -> Any:
        return self.events.serial(*args)

    def bail(self, *args: Any) -> Any:
        return self.events.serial(*args)

    def waterfall(self, *args: Any) -> Any:
        return self.events.waterfall(*args)

    # ------------------------------------------------------------------ 副作用
    def effect(self, execute: Callable[[], Any], label: str = "anonymous") -> Callable[[], None]:
        """注册一个可逆副作用（等价于 ``ctx.fiber.effect``）。"""
        return self.fiber.effect(execute, label)


__all__ = ["Context"]

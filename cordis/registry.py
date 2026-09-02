"""插件注册表。

对应 TypeScript 版的 ``packages/core/src/registry.ts``。

插件有三种形态（与上游一致）：

* **函数** —— ``def apply(ctx, config) -> disposer?``
* **类**   —— ``class Foo(Service)``，构造签名 ``(ctx, config)``
* **对象** —— 带 ``apply(ctx, config)`` 与可选 ``inject`` / ``name`` 属性的实例

``ctx.plugin()`` 返回 :class:`~cordis.fiber.Fiber`，调用它的 ``dispose()`` 即可
完整卸载该插件（包括它内部嵌套注册的所有插件、监听器与自定义副作用）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .fiber import Fiber
from .utils import CordisError, DisposableList, build_outer_stack, is_constructor

#: ``inject`` 的两种写法：``['a', 'b']`` 或 ``{'a': None, 'b': {...}}``
InjectSpec = Iterable[str] | dict[str, Any]


@dataclass
class Runtime:
    """同一个插件（可有多个实例）的共享状态。"""

    name: str | None
    callback: Callable[..., Any]
    fibers: DisposableList = field(default_factory=DisposableList)
    plugin: Any = None
    Config: Callable[[Any], Any] | None = None

    def resolve_config(self, config: Any) -> Any:
        """用插件自带的 ``Config`` 校验/转换配置。"""
        if self.Config is None:
            return config
        return self.Config(config)


def resolve_inject(spec: InjectSpec | None) -> dict[str, Any]:
    """把 ``inject`` 声明摊平成 ``{服务名: 配置}``。"""
    result: dict[str, Any] = {}
    if spec is None:
        return result
    if isinstance(spec, dict):
        for key, value in spec.items():
            result[key] = value
    else:
        for key in spec:
            result[key] = None
    return result


def _class_inject(plugin: Any) -> dict[str, Any]:
    """沿 MRO 合并类上的 ``inject``（等价于上游的原型链查找）。"""
    result: dict[str, Any] = {}
    chain = list(getattr(plugin, "__mro__", [plugin]))
    for klass in reversed(chain):
        spec = klass.__dict__.get("inject")
        if spec is not None:
            result.update(resolve_inject(spec))
    return result


def inject(*deps: str, **configs: Any) -> Callable[[Any], Any]:
    """给函数式插件声明依赖。

    用法::

        @inject('settings', 'themes')
        def apply(ctx, config): ...
    """

    def decorator(target: Any) -> Any:
        spec: dict[str, Any] = {name: None for name in deps}
        spec.update(configs)
        target.inject = spec
        return target

    return decorator


class RegistryService:
    """``ctx.registry`` —— 插件的注册与生命周期管理。"""

    def __init__(self, ctx: "Any") -> None:
        self.ctx = ctx
        self._counter = 0
        self._internal: dict[Callable[..., Any], Runtime] = {}

    # ------------------------------------------------------------------ 元信息
    @property
    def counter(self) -> int:
        self._counter += 1
        return self._counter

    @property
    def size(self) -> int:
        return len(self._internal)

    def resolve(self, plugin: Any) -> Callable[..., Any] | None:
        """把任意形态的插件解析成可调用的 callback。"""
        if is_constructor(plugin) or callable(plugin):
            return plugin
        apply_ = getattr(plugin, "apply", None)
        if callable(apply_):
            return apply_
        return None

    def get(self, plugin: Any) -> Runtime | None:
        key = self.resolve(plugin)
        return self._internal.get(key) if key is not None else None

    def has(self, plugin: Any) -> bool:
        key = self.resolve(plugin)
        return key is not None and key in self._internal

    def keys(self) -> list[Callable[..., Any]]:
        return list(self._internal.keys())

    def values(self) -> list[Runtime]:
        return list(self._internal.values())

    def items(self) -> list[tuple[Callable[..., Any], Runtime]]:
        return list(self._internal.items())

    # ------------------------------------------------------------------ 注册
    def plugin(self, plugin: Any, config: Any = None, ctx: "Any" = None) -> Fiber:
        """加载一个插件，返回它的 Fiber。"""
        ctx = ctx or self.ctx
        callback = self.resolve(plugin)
        if callback is None:
            raise CordisError(
                "INVALID_PLUGIN",
                "invalid plugin, expect callable, class, or object with an "
                f'"apply" method, received {type(plugin).__name__}',
            )
        ctx.fiber.assert_active()

        runtime = self._internal.get(callback)
        if runtime is None:
            runtime = Runtime(
                name=_plugin_name(plugin),
                callback=callback,
                plugin=plugin,
                Config=getattr(plugin, "Config", None),
            )
            self._internal[callback] = runtime

        inject_spec: dict[str, Any]
        if is_constructor(plugin):
            inject_spec = _class_inject(plugin)
        else:
            inject_spec = resolve_inject(getattr(plugin, "inject", None))

        return Fiber(ctx, config, inject_spec, runtime, build_outer_stack)

    def inject(
        self, deps: InjectSpec, callback: Callable[..., Any], ctx: "Any" = None
    ) -> Fiber:
        """依赖满足后执行一次回调（一次性插件）。"""
        return self.plugin(
            _CallbackPlugin(inject=resolve_inject(deps), apply_=callback), None, ctx
        )

    def delete(self, plugin: Any) -> Runtime | None:
        """卸载某个插件的**全部**实例。"""
        key = self.resolve(plugin)
        if key is None:
            return None
        runtime = self._internal.pop(key, None)
        if runtime is None:
            return None
        for fiber in list(runtime.fibers):
            fiber.dispose()
        return runtime


class _CallbackPlugin:
    """``ctx.inject()`` 内部用的临时插件对象。"""

    def __init__(self, inject: dict[str, Any], apply_: Callable[..., Any]) -> None:
        self.inject = inject
        self._apply = apply_
        self.name = getattr(apply_, "__name__", "inject")

    def apply(self, ctx: "Any", config: Any = None) -> Any:
        return self._apply(ctx)


def _plugin_name(plugin: Any) -> str | None:
    name = getattr(plugin, "name", None)
    if name == "apply":
        name = None
    if not name:
        name = getattr(plugin, "__name__", None)
    if name in ("<lambda>", "_CallbackPlugin"):
        name = None
    return name


__all__ = [
    "InjectSpec",
    "RegistryService",
    "Runtime",
    "inject",
    "resolve_inject",
]

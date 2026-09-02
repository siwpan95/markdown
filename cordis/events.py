"""类型化事件系统。

对应 TypeScript 版的 ``packages/core/src/events.ts``，提供五种分发模式：

===========  ==========================================================
``emit``     广播，不收集返回值，任一监听器抛错会向上冒泡
``parallel`` 广播，收集所有异常后以 ``ExceptionGroup`` 抛出（见下方说明）
``serial``   串行，遇到第一个非 ``None/False`` 的返回值就短路
``bail``     串行，遇到第一个非 ``None/False`` 的返回值就短路（不等待）
``waterfall``  洋葱模型：监听器拿到 ``next``，可选择放行、短路或改写参数
===========  ==========================================================

两点与上游的差异（刻意保留，均已在此注明）：

1. **``parallel`` 是同步的。** 上游用 ``Promise.allSettled`` 并行等待；本环境
   跑在 Tkinter 的同步事件循环里，并行没有意义。实现改为“全部执行完再
   汇总异常”，语义上等价于 ``allSettled`` 的错误聚合部分。
2. **``thisArg`` 作为首个位置参数传入。** JavaScript 用 ``this`` 绑定，Python
   没有对应机制。约定：以 ``ctx.emit(ctx, 'evt', ...)`` 形式派发的事件，
   监听器签名为 ``listener(ctx, *args)``；不带 thisArg 派发的事件则
   直接是 ``listener(*args)``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from .utils import DisposableList, symbols

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context
    from .fiber import Fiber


def is_bailed(value: Any) -> bool:
    """``None`` / ``False`` 视为“未处理”，其余都算短路值。"""
    return value is not None and value is not False


@dataclass
class Hook:
    """一个已注册的监听器。"""

    ctx: "Context"
    callback: Callable[..., Any]
    prepend: bool = False
    global_: bool = False
    label: str = ""


class EventsService:
    """``ctx.events`` —— 事件的注册与分发。"""

    #: 本服务自己产生的内部事件，不参与 ``internal/dispatch`` 转发
    INTERNAL_PREFIX = "internal/"

    def __init__(self, ctx: "Context") -> None:
        self.ctx = ctx
        self._hooks: dict[str, list[Hook]] = {}

        # ``internal/update`` 需要按 Fiber 分组：插件注册在自家 fiber 上的
        # update 钩子只应影响该 fiber 自身的配置更新，因此单独存放。
        def _on_listener(this_ctx: "Context", name: str, listener: Any, options: dict) -> Any:
            if name == "internal/update" and not options.get("global_"):
                hooks = this_ctx.fiber._hooks.setdefault(name, DisposableList())
                if options.get("prepend"):
                    hooks.insert(0, listener)
                else:
                    hooks.append(listener)
                return lambda: hooks.delete(listener)
            return None

        def _on_update(
            fiber: "Fiber", config: Any, no_save: bool, next_: Callable[[], Any]
        ) -> Any:
            cbs = list((fiber._hooks.get("internal/update") or []))

            def chain() -> Any:
                cb = cbs.pop(0) if cbs else None
                if cb is None:
                    return next_()
                return cb(config, no_save, chain)

            return chain()

        # 直接写入 _hooks，绕过 fiber.effect —— 这两个钩子生命周期同 ctx
        self._hooks["internal/listener"] = [
            Hook(ctx=ctx, callback=_on_listener, global_=True)
        ]
        self._hooks["internal/update"] = [
            Hook(ctx=ctx, callback=_on_update, global_=True, prepend=True)
        ]

    # ------------------------------------------------------------------ 解析
    def _resolve(self, args: tuple) -> tuple[Any, str, list[Any]]:
        """拆分 ``(thisArg?, name, *rest)``。"""
        this_arg: Any = None
        rest: list[Any] = list(args)
        if len(rest) >= 2 and getattr(rest[0], "__cordis_scope__", False):
            this_arg = rest.pop(0)
        name = rest.pop(0)
        if not str(name).startswith(self.INTERNAL_PREFIX):
            if self._hooks.get("internal/dispatch"):
                self.emit("internal/dispatch", "emit", name, rest, this_arg)
        return this_arg, str(name), rest

    def _callbacks(self, this_arg: Any, name: str) -> list[Callable[..., Any]]:
        hooks = self._hooks.get(name) or []
        if this_arg is None:
            return [hook.callback for hook in hooks]
        own = getattr(this_arg, "_own", None)
        filter_ = own.get(symbols.filter) if own is not None else None
        result = []
        for hook in hooks:
            if hook.global_:
                result.append(hook.callback)
            elif filter_ is None or filter_(hook.ctx):
                result.append(hook.callback)
        return result

    def _apply(self, callback: Callable[..., Any], this_arg: Any, args: list[Any]) -> Any:
        if this_arg is None:
            return callback(*args)
        return callback(this_arg, *args)

    # ------------------------------------------------------------------ 分发
    def emit(self, *args: Any) -> None:
        this_arg, name, rest = self._resolve(args)
        for callback in self._callbacks(this_arg, name):
            self._apply(callback, this_arg, rest)

    def parallel(self, *args: Any) -> None:
        this_arg, name, rest = self._resolve(args)
        errors: list[BaseException] = []
        for callback in self._callbacks(this_arg, name):
            try:
                self._apply(callback, this_arg, rest)
            except Exception as error:  # noqa: BLE001
                errors.append(error)
        if errors:
            raise ExceptionGroup("cordis parallel dispatch failed", errors)  # type: ignore[name-defined]  # noqa: F821

    def serial(self, *args: Any) -> Any:
        this_arg, name, rest = self._resolve(args)
        for callback in self._callbacks(this_arg, name):
            result = self._apply(callback, this_arg, rest)
            if is_bailed(result):
                return result
        return None

    #: 同步实现下与 ``serial`` 等价，保留名字以对齐上游语义
    bail = serial

    def waterfall(self, *args: Any) -> Any:
        this_arg, name, rest = self._resolve(args)
        inner = rest.pop()
        callbacks = self._callbacks(this_arg, name)
        iterator = iter(callbacks)

        def next_() -> Any:
            callback = next(iterator, None)
            if callback is None:
                return inner(*rest)
            return self._apply(callback, this_arg, rest + [next_])

        return next_()

    # ------------------------------------------------------------------ 注册
    def register(
        self,
        label: str,
        hooks: list[Hook],
        callback: Callable[..., Any],
        ctx: "Context | None" = None,
        *,
        prepend: bool = False,
        global_: bool = False,
    ) -> Callable[[], bool]:
        ctx = ctx or self.ctx

        def body() -> Callable[[], bool]:
            hook = Hook(
                ctx=ctx,
                callback=callback,
                prepend=prepend,
                global_=global_,
                label=label,
            )
            if prepend:
                hooks.insert(0, hook)
            else:
                hooks.append(hook)
            return lambda: self.unregister(hooks, callback)

        return ctx.fiber.effect(body, label)

    def unregister(self, hooks: list[Hook], callback: Callable[..., Any]) -> bool:
        for index, hook in enumerate(hooks):
            if hook.callback is callback:
                hooks.pop(index)
                return True
        return False

    def on(
        self,
        name: str,
        listener: Callable[..., Any],
        ctx: "Context | None" = None,
        *,
        prepend: bool = False,
        global_: bool = False,
    ) -> Callable[[], bool]:
        """注册监听器；返回的 disposer 由所属 Fiber 自动管理。"""
        ctx = ctx or self.ctx
        ctx.fiber.assert_active()

        special = self.bail(
            ctx,
            "internal/listener",
            name,
            listener,
            {"prepend": prepend, "global_": global_},
        )
        if special:
            return special

        hooks = self._hooks.setdefault(name, [])
        label = f"ctx.on({name!r})"
        return self.register(
            label,
            hooks,
            listener,
            ctx,
            prepend=prepend,
            global_=global_,
        )

    def once(
        self,
        name: str,
        listener: Callable[..., Any],
        ctx: "Context | None" = None,
        *,
        prepend: bool = False,
        global_: bool = False,
    ) -> Callable[[], bool]:
        """注册一次性监听器。"""
        disposer: Callable[[], bool] | None = None

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if disposer is not None:
                disposer()
            return listener(*args, **kwargs)

        disposer = self.on(
            name, wrapper, ctx, prepend=prepend, global_=global_
        )
        return disposer

    # ------------------------------------------------------------------ 内省
    def hooks(self, name: str) -> list[Hook]:
        return list(self._hooks.get(name) or [])

    def hook_count(self) -> int:
        return sum(len(v) for v in self._hooks.values())


__all__ = ["EventsService", "Hook", "is_bailed"]

"""Fiber —— 插件的执行域与生命周期状态机。

对应 TypeScript 版的 ``packages/core/src/fiber.ts``。

一个 Fiber 就是“一次插件加载”：它持有插件的配置、依赖快照（``inject``）、
以及这次加载过程中产生的全部副作用（``effect``）。核心不变量只有一条——

    **Fiber 被卸载时，它注册过的每一个副作用都必须被调用一次。**

上游是异步的（``await`` 编排），这里改成同步：Tkinter 的事件循环本身是同步的，
异步编排反而会引入重入问题。除了“同步 vs 异步”，状态机、epoch 比对、
逆序清理的语义与上游保持一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Callable

from .utils import (
    CordisError,
    DisposableList,
    build_outer_stack,
    compose_error,
    is_constructor,
    is_nullable,
    symbols,
    to_disposables,
)

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context
    from .registry import Plugin


class FiberState(IntEnum):
    """插件生命周期。

    合法转换::

        PENDING --依赖就绪--> LOADING --执行成功--> ACTIVE
                                     \\--执行失败--> FAILED
        ACTIVE  --依赖消失--> UNLOADING --> PENDING
        ACTIVE  --卸载------> DISPOSED
    """

    PENDING = 0
    LOADING = 1
    ACTIVE = 2
    FAILED = 3
    DISPOSED = 4
    UNLOADING = 5


#: 依赖未满足时使用的哨兵 epoch
INACTIVE = "__INACTIVE__"


@dataclass
class EffectMeta:
    """副作用的调试信息。"""

    label: str
    children: list["EffectMeta"] = field(default_factory=list)


class Fiber:
    """一次插件加载的执行域。"""

    #: 事件分发用的标记：``ctx.waterfall(fiber, 'internal/update', ...)``
    __cordis_scope__ = True

    def __init__(
        self,
        parent: "Context",
        config: Any,
        inject: dict[str, Any],
        runtime: "Plugin.Runtime | None",
        get_outer_stack: Callable[[], list[str]] = build_outer_stack,
    ) -> None:
        self.parent = parent
        self.config = config
        self.inject: dict[str, Any] = inject
        self.runtime = runtime
        self.state = FiberState.PENDING
        self.store: dict[str, Any] | None = None
        self.uid: int | None = None
        #: 由 :mod:`cordis.loader` 填充：本 Fiber 属于哪个配置条目。
        #: 不使用 loader 时恒为 ``None``。
        self.entry: Any = None

        self._hooks: dict[str, DisposableList] = {}
        self._disposables = DisposableList()
        self._store: dict[str, Any] = {}
        self._error: BaseException | None = None
        self._epoch = INACTIVE
        self._loaded = False
        self._loaded_epoch: str | None = None
        self._syncing = False
        self._dirty = False
        self._get_outer_stack = get_outer_stack
        self._effects: list[EffectMeta] = []

        if runtime is None:
            # 根上下文：没有插件，永远 ACTIVE，dispose 等价于重启整棵树
            self.uid = 0
            self.ctx: "Context" = parent
            self.state = FiberState.ACTIVE
            self.store = {}
            self.dispose: Callable[[], Any] = self.restart
            return

        self.uid = parent.registry.counter
        self.ctx = parent.extend({"fiber": self})

        intercepted = {k: v for k, v in inject.items() if not is_nullable(v)}
        if intercepted:
            self.ctx._own[symbols.intercept] = parent._intercept.extend(intercepted)

        self.ctx.emit("internal/plugin", self)
        for name in inject:
            self._check_impl(name)

        self.dispose = parent.fiber.effect(self._load, "ctx.plugin()")

    # ------------------------------------------------------------------ 元信息
    @property
    def name(self) -> str:
        """插件名；匿名插件回溯到最近的具名祖先，再不行就是 ``root``。"""
        fiber: Fiber = self
        while True:
            if fiber.runtime is not None and fiber.runtime.name:
                return fiber.runtime.name
            parent = fiber.parent.fiber
            if parent is fiber:
                return "root"
            fiber = parent

    @property
    def is_active(self) -> bool:
        return self.state == FiberState.ACTIVE

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<Fiber {self.name} state={self.state.name} uid={self.uid}>"

    def assert_active(self) -> None:
        """在已销毁的上下文里注册副作用时报错。"""
        if self.uid is None:
            raise CordisError(
                "INACTIVE_EFFECT", "cannot create effect on inactive context"
            )

    # ------------------------------------------------------------------ 加载
    def _load(self) -> Callable[[], None]:
        """把本 Fiber 挂进 runtime，并在依赖就绪时执行插件体。"""
        assert self.runtime is not None
        remove = self.runtime.fibers.push(self)
        try:
            self.config = self.runtime.resolve_config(self.config)
            self._refresh()
        except Exception as error:  # noqa: BLE001 - 配置错误也要给出可读信息
            compose_error(self._get_outer_stack())(error)
            self.ctx.logger.error(error)
            self._error = error

        def dispose() -> None:
            self.uid = None
            self.ctx.emit("internal/plugin", self)
            registry = self.ctx.registry
            if registry.has(self.runtime.callback):
                remove()
                if not self.runtime.fibers:
                    registry.delete(self.runtime.callback)
            self._loaded_epoch = None
            self._set_epoch(INACTIVE)

        return dispose

    def _execute(self) -> None:
        """执行插件体，并把返回值收集成 disposer。"""
        assert self.runtime is not None
        callback = self.runtime.callback
        if is_constructor(callback):
            instance = callback(self.ctx, self.config)
            from .service import Service  # 局部导入，避免循环依赖

            if isinstance(instance, Service):
                init = getattr(instance, "init", None)
                if callable(init):
                    init()
            effect: Any = None
        else:
            effect = callback(self.ctx, self.config)

        for dispose in to_disposables(effect):
            self._disposables.push(dispose)

    def _reload(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._loaded_epoch = self._epoch
        self.store = dict(self._store)
        self._error = None
        self._update_state(FiberState.LOADING)
        try:
            self._execute()
        except Exception as error:  # noqa: BLE001
            compose_error(self._get_outer_stack())(error)
            self.ctx.logger.error(error)
            self._error = error
            self._update_state(FiberState.FAILED)
            self._loaded_epoch = None
            return
        if self._epoch == self._loaded_epoch:
            self._update_state(FiberState.ACTIVE)
        else:
            # 执行期间依赖又变了，交给外层的 _sync 循环再对齐一次
            self._dirty = True

    def _unload(self) -> None:
        if not self._loaded:
            return
        self._loaded = False
        self._loaded_epoch = None
        for dispose in reversed(self._disposables.clear()):
            try:
                dispose()
            except Exception as error:  # noqa: BLE001 - 清理失败不应中断其余清理
                self.ctx.logger.error(error)
        self.store = None
        self._update_state(
            FiberState.DISPOSED if self.uid is None else FiberState.PENDING
        )

    # ------------------------------------------------------------------ 依赖
    def _check_impl(self, name: str) -> None:
        """检查某个被注入的服务当前是否可用。"""
        impl = self.ctx.reflect._get_impl(name, strict=True, ctx=self.ctx)
        if impl is None:
            self._store.pop(name, None)
            return
        try:
            if impl.check is not None and not impl.check(impl.value):
                self._store.pop(name, None)
                return
        except Exception as error:  # noqa: BLE001
            impl.fiber.ctx.logger.error(error)
            self._store.pop(name, None)
            return
        self._store[name] = impl

    def _refresh(self) -> None:
        """按当前依赖快照重算 epoch；任一依赖缺失则整体停用。"""
        epoch = ""
        for name in self.inject:
            impl = self._store.get(name)
            if impl is None:
                epoch = INACTIVE
                break
            epoch += ":" + str(impl.fiber.uid)
        self._set_epoch(epoch)

    def _set_epoch(self, epoch: str) -> None:
        if epoch == self._epoch:
            return
        self._epoch = epoch
        self._sync()

    def _sync(self) -> None:
        """把状态对齐到当前 epoch。

        依赖变化可能在加载过程中再次发生（A 提供服务 → B 加载 → B 又让 C 可用），
        因此这里用 ``_dirty`` 循环而不是单次判断。``_syncing`` 用于防止循环依赖
        把调用栈打爆：重入时只置脏标记，由最外层循环继续收敛。
        """
        if self._syncing:
            self._dirty = True
            return
        self._syncing = True
        try:
            while True:
                self._dirty = False
                should_load = self._epoch != INACTIVE and self.uid is not None
                if self._loaded and (not should_load or self._loaded_epoch != self._epoch):
                    self._unload()
                if should_load and not self._loaded:
                    self._reload()
                if not self._dirty:
                    return
        finally:
            self._syncing = False

    # ------------------------------------------------------------------ 副作用
    def effect(
        self, execute: Callable[[], Any], label: str = "anonymous"
    ) -> Callable[[], None]:
        """注册一个可逆副作用。

        ``execute`` 的返回值可以是 ``None``、一个 disposer、disposer 序列，
        或者 ``yield`` 出多个 disposer 的生成器。Fiber 卸载时，这些 disposer
        会按**注册的逆序**被调用。
        """
        self.assert_active()

        local: list[Callable[[], Any]] = []
        done = False

        def collect(dispose: Callable[[], Any]) -> None:
            local.append(dispose)
            self._disposables.delete(dispose)

        def dispose_local() -> None:
            for dispose in reversed(local):
                dispose()

        try:
            for dispose in to_disposables(execute()):
                collect(dispose)
        except Exception:
            # 注册到一半失败：立刻回滚已经收集的部分，不留残局
            dispose_local()
            raise

        def wrapper() -> None:
            nonlocal done
            if done:
                return
            done = True
            dispose_local()

        wrapper.effect_meta = EffectMeta(label=label)  # type: ignore[attr-defined]
        local.append(self._disposables.push(wrapper))
        self._effects.append(wrapper.effect_meta)  # type: ignore[attr-defined]
        return wrapper

    def get_effects(self) -> list[EffectMeta]:
        """返回本 Fiber 上所有具名副作用（用于调试面板）。"""
        return list(self._effects)

    # ------------------------------------------------------------------ 状态
    def _get_state(self) -> FiberState:
        if self.uid is None:
            return FiberState.DISPOSED
        if self._error is not None:
            return FiberState.FAILED
        if self._epoch == INACTIVE:
            return FiberState.PENDING
        return FiberState.ACTIVE

    def _update_state(self, state: FiberState) -> None:
        old = self.state
        self.state = state
        if old == state:
            return
        self.ctx.emit("internal/status", self, old)
        # 只在「活跃 ↔ 非活跃」之间切换时通知依赖方
        if (old == FiberState.ACTIVE) == (state == FiberState.ACTIVE):
            return
        reflect = self.ctx.root.reflect
        names = [
            impl.name
            for impl in list(reflect.store.values())
            if impl.fiber is self
        ]
        if names:
            reflect.notify(names)

    # ------------------------------------------------------------------ 控制
    def await_(self) -> "Fiber":
        """同步版本没有真正的等待；仅用于在错误时抛出。"""
        if self._error is not None:
            raise self._error
        return self

    def restart(self) -> "Fiber":
        """重启：先卸载再按当前依赖重新加载。"""
        self._set_epoch(INACTIVE)
        self._refresh()
        return self.await_()

    def update(self, config: Any, no_save: bool = False) -> "Fiber":
        """用新配置重启插件。

        配置变更走 :func:`~cordis.events.EventsService.waterfall` 的
        ``internal/update`` 钩子，插件可以用它在保存前做校验或改写。

        :param no_save: 为 ``True`` 时表示「这是由配置驱动的更新」，loader
            不应把它再写回配置文件（否则会形成回环）。
        """
        if self.runtime is None:
            raise CordisError("INVALID_TARGET", "cannot update the root fiber")
        resolved = self.runtime.resolve_config(config)

        def commit(new_config: Any, *_rest: Any) -> None:
            self.config = new_config
            self._error = None
            self.restart()

        self.ctx.waterfall(self, "internal/update", resolved, no_save, commit)
        return self.await_()


__all__ = ["EffectMeta", "Fiber", "FiberState", "INACTIVE"]

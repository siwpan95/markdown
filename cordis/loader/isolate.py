"""声明式的服务隔离与配置覆写。

对应上游 ``packages/loader/src/config/isolate.ts``。

配置文件里的条目可以声明::

    - id: preview
      name: mdviewer.plugins.preview
      isolate:
        documents: true        # 本条目独享一份 documents 服务
      intercept:
        themes: { key: dark }  # 本条目看到的 themes 配置被覆写

机制上只是把 :meth:`Context.isolate` / :meth:`Context.intercept` 的产物预先算好，
写进条目自己的上下文，再让它下面的 Fiber 加载。

**与上游的差异（已简化）**：上游额外维护了 ``Realm``（局部 / 全局作用域）与
一组 delimiter symbol，用于在 isolate 变更时把已有的服务实例在作用域之间“过户”，
避免重新创建。本项目没有多租户场景，过户带来的正确性收益不值那份复杂度，
因此未移植——isolate 变更后相关插件会按 Cordis 的正常流程卸载重载。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..utils import Symbol, symbols
from .entry import ENTRY_KEY

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context


def apply(ctx: "Context", config: Any = None) -> None:
    """注册 isolate / intercept 的配置钩子。"""
    realms: dict[str, dict[str, Symbol]] = {}

    def access(entry: Any, name: str, create: bool) -> Symbol | None:
        label = (entry.options.get("isolate") or {}).get(name)
        if not label:
            return None
        if label is True:
            realm = getattr(entry, "realm", None)
            if realm is None:
                realm = {}
                entry.realm = realm
        else:
            realm = realms.setdefault(str(label), {})
        key = realm.get(name)
        if key is None and create:
            key = Symbol(f"{name}#{label}")
            realm[name] = key
        return key

    def on_entry_init(entry: Any) -> None:
        """给每个条目一份独立的 isolate / intercept 映射。

        条目刚构造时还没有归组（``entry.parent`` 尚不存在），此时以 loader
        自己的上下文为基准。
        """
        parent_ctx = getattr(entry, "parent_ctx", None) or ctx
        entry.ctx._own[symbols.isolate] = parent_ctx._isolate.extend()
        entry.ctx._own[symbols.intercept] = parent_ctx._intercept.extend()

    def on_patch_context(entry: Any, next_: Any) -> None:
        """重新加载 Fiber 之前，先把 isolate / intercept 映射刷新到最新配置。"""
        isolate_map: dict[str, Symbol] = {}
        for name in (entry.options.get("isolate") or {}):
            key = access(entry, name, True)
            if key is not None:
                isolate_map[name] = key
        entry.ctx._own[symbols.isolate] = entry.ctx._isolate.extend(isolate_map)
        entry.ctx._own[symbols.intercept] = entry.ctx._intercept.extend(
            dict(entry.options.get("intercept") or {})
        )
        return next_()

    def on_partial_dispose(entry: Any, legacy: dict[str, Any], active: bool) -> None:
        """条目被移除 / 隔离变更时，回收不再被引用的全局 realm。"""
        legacy_isolate = legacy.get("isolate") or {}
        for name, label in legacy_isolate.items():
            if label is True:
                continue
            current = (entry.options.get("isolate") or {}).get(name)
            if active and current == label:
                continue
            realm = realms.get(str(label))
            if realm is None:
                continue
            still_used = any(
                (e.options.get("isolate") or {}).get(name) == label
                for e in ctx.loader.entries()
            )
            if still_used:
                continue
            realm.pop(name, None)
            if not realm:
                realms.pop(str(label), None)

    ctx.on("loader/entry-init", on_entry_init, global_=True)
    ctx.on("loader/patch-context", on_patch_context, global_=True)
    ctx.on("loader/partial-dispose", on_partial_dispose, global_=True)


apply.name = "isolate"
_ = ENTRY_KEY  # 保留引用，静态检查用

__all__ = ["apply"]

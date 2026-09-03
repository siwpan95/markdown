"""配置条目 —— 一个「插件 + 它的配置」的运行时单元。

对应上游 ``packages/loader/src/config/entry.ts``。

Entry 是 loader 的核心抽象：它把配置文件里的一行（``{id, name, config, …}``）
和一个真正在跑的 :class:`~cordis.fiber.Fiber` 绑在一起，于是：

* 改配置 → 找到 Entry → diff → ``fiber.update()``，**不需要重启进程**；
* 关掉 ``disabled`` → ``fiber.dispose()``，副作用按 Cordis 的规矩全部回滚；
* 插件自己 ``ctx.fiber.dispose()`` → loader 会捕捉到并把 ``disabled`` 写回配置
  （见 :class:`~cordis.loader.Loader` 里的 ``internal/plugin`` 处理）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..utils import CordisError, Symbol
from .utils import diff_keys, interpolate, sort_keys

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..fiber import Fiber
    from .group import EntryGroup
    from .tree import EntryTree

#: 存在 Context 上的条目标记，插件可以顺着 fiber 链找到自己属于哪个 entry
ENTRY_KEY = Symbol.for_name("cordis.entry")


class Entry:
    """一个配置条目。"""

    def __init__(self, loader: "Any") -> None:
        self.loader = loader
        self.parent: "EntryGroup"  # 由 EntryGroup.create() 立即赋值
        self.ctx: "Context" = loader.ctx.extend({ENTRY_KEY: self})
        self.fiber: "Fiber | None" = None
        self.options: dict[str, Any] = {}
        self.subgroup: "EntryGroup | None" = None
        self.subtree: "EntryTree | None" = None
        self.ctx.emit("loader/entry-init", self)

    # ------------------------------------------------------------------ 元信息
    @property
    def parent_ctx(self) -> "Context | None":
        """父分组的上下文；条目刚构造、还没归组时为 ``None``。"""
        parent = getattr(self, "parent", None)
        return getattr(parent, "ctx", None) if parent is not None else None

    @property
    def parent_entry(self) -> "Entry | None":
        """父分组所属的条目（嵌套组时非空）。"""
        ctx = self.parent_ctx
        return getattr(ctx.fiber, "entry", None) if ctx is not None else None

    @property
    def id(self) -> str:
        """完整 id，嵌套组用 ``:`` 连接（如 ``ui:find``）。"""
        from .tree import EntryTree

        own = str(self.options.get("id", ""))
        parent = self.parent_entry
        if parent is not None:
            return f"{parent.id}{EntryTree.sep}{own}"
        return own

    @property
    def disabled(self) -> bool:
        """自身或任一祖先被禁用即为禁用；分组本身永远视为启用。"""
        if self.options.get("group"):
            return False
        entry: "Entry | None" = self
        while entry is not None:
            if entry.options.get("disabled"):
                return True
            entry = entry.parent_entry
        return False

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<Entry {self.id} name={self.options.get('name')!r}>"

    # ------------------------------------------------------------------ 配置
    def resolve_config(self, plugin: Any) -> Any:
        """取出本条目的配置，并做 ``$env`` 插值。"""
        if getattr(plugin, "IS_GROUP", False):
            # 分组插件拿到的 config 就是子条目列表，不能插值
            return self.options.get("config")
        return interpolate(self.options.get("config"))

    def get_outer_stack(self) -> list[str]:
        """出错时给出「哪个配置条目」的上下文，而不是一堆框架内部帧。"""
        from .tree import EntryTree

        result: list[str] = []
        entry: "Entry | None" = self
        while entry is not None:
            tree = getattr(getattr(entry, "parent", None), "tree", None)
            base = getattr(tree.ctx, "base_url", "") if tree is not None else ""
            result.append(f"    at {base}#{entry.options.get('id')}")
            entry = entry.parent_entry
        _ = EntryTree  # 保持引用，便于静态检查
        return result

    # ------------------------------------------------------------------ 生命周期
    def refresh(self) -> None:
        """依赖或分组状态变化后，按需重新加载。"""
        if self.fiber is not None or self.disabled:
            return
        self.init()

    def update(
        self,
        options: dict[str, Any],
        create: bool = False,
        force: bool = False,
    ) -> None:
        """合并配置并让 Fiber 跟上。"""
        legacy = dict(self.options)

        if create:
            self.options = dict(options)
        else:
            for key, value in options.items():
                if value is None:
                    self.options.pop(key, None)
                else:
                    self.options[key] = value
        sort_keys(self.options)

        if self.disabled:
            if self.fiber is not None:
                self.fiber.dispose()
            return

        if self.fiber is not None and self.fiber.uid is not None:
            diff = diff_keys(self.options, legacy)
            if not diff and not force:
                return
            self.ctx.emit("loader/partial-dispose", self, legacy, True)
            self._patch_context(diff)
        else:
            self.init()

    def _patch_context(self, diff: list[str]) -> None:
        """把改动落到运行中的 Fiber 上。

        包一层 waterfall 事件，好让 ``isolate`` 之类的插件有机会先改写
        isolate / intercept 映射，再触发 reload。
        """

        def next_(*_rest: Any) -> None:
            if self.fiber is not None and self.fiber.uid is not None and (
                "config" in diff or self.options.get("group")
            ):
                plugin = self.fiber.runtime.callback if self.fiber.runtime else None
                self.fiber.update(self.resolve_config(plugin), True)

        self.ctx.waterfall("loader/patch-context", self, next_)

    def init(self) -> None:
        """按配置加载插件。

        注意 ``self.fiber`` 在插件被停用后**不会**自动清空——它仍指向那个 uid
        已经归零的死 Fiber。因此这里要按 uid 判断，否则重新启用会静默失败。
        """
        if (self.fiber is not None and self.fiber.uid is not None) or self.disabled:
            return
        name = self.options.get("name")
        if not name:
            self.ctx.logger.error("配置条目缺少 name：%s", self.options)
            return
        try:
            exports = self.parent.tree.import_plugin(name, self.get_outer_stack)
        except Exception as error:  # noqa: BLE001 - 加载失败要让其它条目继续
            self.ctx.logger.error(error)
            return

        plugin = self.loader.unwrap_exports(exports)
        if plugin is None:
            self.ctx.logger.error("配置条目 %s 没有找到可执行的插件对象", name)
            return

        self._patch_context([])
        self.loader.show_log(self, "apply")
        self.fiber = self.ctx.plugin(
            plugin, self.resolve_config(plugin), self.get_outer_stack
        )

    # ------------------------------------------------------------------ 写回
    def write_config(self, config: Any) -> None:
        """插件自己改了配置时，回写到 options 并触发持久化。"""
        self.options["config"] = config
        sort_keys(self.options)
        self.parent.tree.write()


__all__ = ["ENTRY_KEY", "Entry"]

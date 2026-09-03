"""配置分组。

对应上游 ``packages/loader/src/config/group.ts``。

一个分组就是一份**有序的条目列表**。``update()`` 把新配置与旧配置按 ``id``
做差量：新出现的创建、消失的销毁、都有的递归更新。所有销毁都走
``fiber.dispose()``，副作用照例完整回滚。

``Group`` 本身也是一个插件（``IS_GROUP = True``）：配置里写
``{"id": "ui", "name": "cordis:group", "config": [...]}`` 就能把若干插件收进一个
可整体启停的子树，子条目的 id 会自动变成 ``ui:find`` 这样的路径形式。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .entry import Entry

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from .tree import EntryTree


class EntryGroup:
    """一组配置条目。"""

    def __init__(self, ctx: "Context", tree: "EntryTree") -> None:
        self.ctx = ctx
        self.tree = tree
        self.data: list[dict[str, Any]] = []
        entry = getattr(ctx.fiber, "entry", None)
        if entry is not None:
            entry.subgroup = self

    # ------------------------------------------------------------------ 增删
    def create(self, options: dict[str, Any]) -> str:
        """创建（或复用）一个条目并立即加载。"""
        entry_id = self.tree.ensure_id(options)
        entry = self.tree.store.get(entry_id)
        if entry is None:
            entry = Entry(self.ctx.loader)
            self.tree.store[entry_id] = entry
        # 条目可能从别的分组搬过来，父引用要跟着更新
        entry.parent = self
        entry.update(options, create=True, force=True)
        return entry.id

    def unlink(self, options: dict[str, Any]) -> None:
        """只从配置数据里摘掉，不动运行时。"""
        if options in self.data:
            self.data.remove(options)

    def remove(self, entry_id: str, is_dispose: bool = False) -> None:
        """销毁一个条目（含它的 Fiber）。"""
        entry = self.tree.store.get(entry_id)
        if entry is None:
            return
        if entry.fiber is not None:
            entry.fiber.dispose()
        if not is_dispose:
            self.unlink(entry.options)
        self.tree.store.pop(entry_id, None)
        self.ctx.emit("loader/partial-dispose", entry, entry.options, False)

    # ------------------------------------------------------------------ 更新
    def update(self, config: list[dict[str, Any]]) -> None:
        """按 id 做差量更新。"""
        old_map = {str(o.get("id")): o for o in self.data}
        new_map = {str(o.get("id")): o for o in config}
        self.data = list(config)

        # 按「旧配置顺序 + 新增项顺序」遍历，保证每次更新的加载次序稳定
        ordered = [i for i in old_map if i in old_map]
        ordered += [i for i in new_map if i not in old_map]
        for entry_id in ordered:
            if entry_id in new_map:
                try:
                    self.create(new_map[entry_id])
                except Exception as error:  # noqa: BLE001 - 单个条目失败不影响其它
                    self.ctx.logger.error(error)
            else:
                self.remove(entry_id)

    def stop(self) -> None:
        """停掉整组（不改动配置数据，用于服务卸载）。"""
        for options in list(self.data):
            self.remove(str(options.get("id")), is_dispose=True)


class Group:
    """分组插件：``config`` 是一份子条目列表。

    用法（配置文件里）::

        {"id": "ui", "name": "cordis:group", "config": [
            {"id": "find", "name": "mdviewer.plugins.find"},
            {"id": "toc",  "name": "mdviewer.plugins.toc", "disabled": true}
        ]}
    """

    #: loader 用这个标记识别分组插件（分组的 config 是一份列表，不做 $env 插值）
    IS_GROUP = True
    name = "group"

    def __init__(self, ctx: "Context", config: list[dict[str, Any]] | None = None) -> None:
        self.ctx = ctx
        entry = getattr(ctx.fiber, "entry", None)
        tree = entry.parent.tree if entry is not None else ctx.loader.root.tree
        self.group = EntryGroup(ctx, tree)

        # 分组插件被卸载时，整组条目一起停掉
        ctx.effect(lambda: self.group.stop, "group:stop")
        ctx.on("internal/update", self._on_update)
        self.group.update(list(config or []))

    def _on_update(self, config: Any, *_rest: Any) -> None:
        """配置热更新：整份子条目列表被替换时重新做差量。"""
        if isinstance(config, list):
            self.group.update(config)


__all__ = ["EntryGroup", "Group"]

"""配置树。

对应上游 ``packages/loader/src/config/tree.ts``。

``EntryTree`` 持有全部条目（``store``）与根分组（``root``），负责：

* 按 ``id`` 解析条目 / 分组（嵌套用 ``:`` 分隔，如 ``ui:find``）；
* 把配置里的 ``name`` 解析成可执行的插件对象（内置名 / 模块名 / 文件路径）；
* ``write()`` 是一个抽象方法——根树的写入是空操作（内存态），需要持久化的
  （例如把配置写回文件）由子类实现。
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from ..utils import CordisError
from .group import EntryGroup

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from .entry import Entry

#: 内置插件名的前缀：``cordis:group`` → ``builtins["group"]``
BUILTIN_PREFIX = "cordis:"


class EntryTree:
    """一份配置树（可嵌套）。"""

    sep = ":"

    def __init__(self, ctx: "Context") -> None:
        self.ctx = ctx.extend({"base_url": ctx.base_url})
        self.root = EntryGroup(self.ctx, self)
        self.store: dict[str, "Entry"] = {}
        entry = getattr(ctx.fiber, "entry", None)
        if entry is not None:
            entry.subtree = self

    # ------------------------------------------------------------------ 遍历
    def entries(self) -> "Iterator[Entry]":
        """深度优先遍历全部条目（含子树的）。"""
        for entry in list(self.store.values()):
            yield entry
            if entry.subtree is None:
                continue
            yield from entry.subtree.entries()

    # ------------------------------------------------------------------ 解析
    def ensure_id(self, options: dict[str, Any]) -> str:
        """给缺 id 的条目补一个随机 id（8 位十六进制）。"""
        if not options.get("id"):
            import secrets

            while True:
                candidate = secrets.token_hex(4)
                if candidate not in self.store:
                    options["id"] = candidate
                    break
        return str(options["id"])

    def resolve(self, entry_id: str) -> "Entry":
        """按 id 找条目。

        支持两种写法：

        * 完整路径 ``ui:off`` —— 逐段走进子分组；
        * 叶子 id ``off`` —— 嵌套条目其实也存在同一份扁平 ``store`` 里，
          因此直接用叶子 id 也能解析（上游只支持前者，这里放宽了）。

        上游的 ``subtree`` 只在「子配置文件」场景下才有；内存里的 :class:`Group`
        只有 ``subgroup``，因此这里两者都认。
        """
        parts = entry_id.split(self.sep)
        final = parts.pop()
        tree: EntryTree | None = self
        for part in parts:
            if tree is None:
                raise CordisError("ENTRY_NOT_FOUND", f"cannot resolve entry {entry_id}")
            entry = tree.store.get(part)
            subtree = entry.subtree if entry is not None else None
            if subtree is None and entry is not None and entry.subgroup is not None:
                subtree = entry.subgroup.tree
            tree = subtree
        if tree is None:
            raise CordisError("ENTRY_NOT_FOUND", f"cannot resolve entry {entry_id}")
        entry = tree.store.get(final) or self.store.get(final)
        if entry is None:
            raise CordisError("ENTRY_NOT_FOUND", f"cannot resolve entry {entry_id}")
        return entry

    def resolve_group(self, entry_id: str | None) -> EntryGroup:
        """按 id 找分组；``None`` 表示根分组。"""
        if not entry_id:
            return self.root
        entry = self.resolve(entry_id)
        if entry.subgroup is None:
            raise CordisError("NOT_A_GROUP", f"entry {entry_id} is not a group")
        return entry.subgroup

    # ------------------------------------------------------------------ 编辑
    def create(
        self,
        options: dict[str, Any],
        parent: str | None = None,
        position: int | None = None,
    ) -> str:
        group = self.resolve_group(parent)
        index = len(group.data) if position is None else position
        group.data.insert(index, options)
        self.write()
        return group.create(options)

    def remove(self, entry_id: str) -> None:
        entry = self.resolve(entry_id)
        entry.parent.remove(entry_id.split(self.sep)[-1])
        entry.parent.tree.write()

    def update(
        self,
        entry_id: str,
        options: dict[str, Any],
        parent: str | None = None,
        position: int | None = None,
    ) -> None:
        entry = self.resolve(entry_id)
        source = entry.parent
        if parent is not None:
            target = self.resolve_group(parent)
            source.unlink(entry.options)
            index = len(target.data) if position is None else position
            target.data.insert(index, entry.options)
            target.tree.write()
            entry.parent = target
        source.tree.write()
        entry.update(options, create=False, force=True)

    # ------------------------------------------------------------------ 导入
    def import_plugin(self, name: str, get_outer_stack: Any = None) -> Any:
        """把配置里的 ``name`` 解析成插件对象（模块 / 对象 / 类 / 函数）。

        解析顺序：

        1. ``cordis:<key>`` → :attr:`Loader.builtins` 里的内置插件；
        2. 裸短名命中 ``builtins`` → 直接用（宿主应用登记的短名，如 ``toc``）；
        3. 以 ``.`` / ``/`` 开头或以 ``.py`` 结尾 → 按文件路径导入；
        4. 其它 → 按模块名 ``importlib.import_module``。
        """
        builtins = getattr(self.ctx.loader, "builtins", {})
        if name.startswith(BUILTIN_PREFIX):
            key = name[len(BUILTIN_PREFIX) :]
            builtin = builtins.get(key)
            if builtin is None:
                raise CordisError("UNKNOWN_BUILTIN", f"未注册的内置插件：{key}")
            return builtin
        if name in builtins:
            builtin = builtins[name]
            self._remember(name, builtin)
            return builtin
        if name.startswith(".") or name.startswith("/") or name.endswith(".py"):
            return self._import_by_path(name)
        return self._import_module(name)

    def _import_module(self, name: str) -> Any:
        module = importlib.import_module(name)
        self._remember(name, module)
        return module

    def _import_by_path(self, name: str) -> Any:
        base = self.ctx.base_url
        path = Path(name)
        if not path.is_absolute() and base:
            path = Path(base) / name
        path = path.resolve()
        if not path.is_file():
            raise CordisError("MODULE_NOT_FOUND", f"找不到插件文件：{path}")
        module_name = f"cordis._loaded_{abs(hash(path)):x}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise CordisError("IMPORT_FAILED", f"无法加载插件文件：{path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        self._remember(module_name, module)
        return module

    def _remember(self, key: str, module: Any) -> None:
        """记录已导入的模块，供 HMR 做依赖分析。"""
        loader = getattr(self.ctx, "loader", None)
        if loader is not None and hasattr(loader, "modules"):
            loader.modules[key] = module

    # ------------------------------------------------------------------ 持久化
    def write(self) -> None:
        """写回配置；根树是内存态，默认空实现。"""
        raise NotImplementedError


def unwrap_exports(exports: Any) -> Any:
    """从模块/命名空间里取出真正的插件对象。

    优先级：``apply`` → ``default`` → ``plugin`` → 模块自身（若有 ``apply``）。
    等价于上游 ``Loader.unwrapExports`` 对 ``module.default`` / ``__esModule``
    的处理。
    """
    if exports is None or inspect.isclass(exports) or inspect.isfunction(exports):
        return exports
    if inspect.ismodule(exports):
        for attr in ("apply", "default", "plugin"):
            candidate = getattr(exports, attr, None)
            if candidate is not None:
                return unwrap_exports(candidate)
        return None
    apply_ = getattr(exports, "apply", None)
    if callable(apply_):
        return exports
    return exports


__all__ = ["BUILTIN_PREFIX", "EntryTree", "unwrap_exports"]

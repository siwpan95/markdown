"""声明式插件加载器。

对应上游 ``@cordisjs/plugin-loader``。

有了它，插件的装配就从「代码里写死一行 ``ctx.plugin(...)``」变成「配置文件里写
一行声明」。这不是语法糖——配置变了会走 ``Entry.update()`` 做差量，只重建真正
变化的那一棵子树，其余插件的状态原样保留。

    >>> ctx = Context()
    >>> ctx.plugin(Loader, {'config': 'cordis.yml'})
    >>> ctx.loader.entries()          # 所有被加载的条目
    >>> ctx.loader.update('find', {'disabled': True})   # 运行时停用
    >>> ctx.loader.create({'name': 'my.plugins.x'})     # 运行时新增

配置文件示例（``cordis.yml`` / ``cordis.json`` / ``cordis.toml``）::

    - id: toc
      name: mdviewer.plugins.toc
    - id: find
      name: mdviewer.plugins.find
      config:
        nocase: true
    - id: ui
      name: cordis:group          # 分组：config 是一份子条目列表
      config:
        - id: status
          name: mdviewer.plugins.status
        - id: toc2
          name: mdviewer.plugins.toc
          disabled: true

``name`` 的解析规则：

* ``cordis:<key>``  → :attr:`Loader.builtins` 里注册的内置插件；
* 以 ``.`` / ``/`` 开头或以 ``.py`` 结尾 → 按文件路径导入（相对 ``base_url``）；
* 其它 → 按模块名 ``importlib.import_module``。

配置值里可以用 ``{"$env": "VAR"}`` 或 ``{"$env": ["VAR", "默认值"]}`` 取环境变量
——**刻意不支持任意表达式求值**，配置文件不是可信输入。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..service import Service
from .config import ConfigError, find_config_file, load_config_file, normalize
from .entry import ENTRY_KEY, Entry
from .group import EntryGroup, Group
from .isolate import apply as isolate
from .tree import EntryTree, unwrap_exports
from .utils import interpolate


class Loader(EntryTree, Service):
    """``ctx.loader`` —— 声明式装配的入口。"""

    name = "loader"
    #: 加载器本身不依赖任何服务，但要等配置就绪
    inject: list[str] = []

    def __init__(self, ctx: "Any", config: Any = None) -> None:
        options = config if isinstance(config, dict) else {}
        self.config = options
        self.env_data: dict[str, Any] = {}
        self.builtins: dict[str, Any] = {"group": Group}
        self.modules: dict[str, Any] = {}
        self.enable_logs = bool(options.get("logs", False))
        self._source: Path | None = None

        # 先占住 ctx.loader 这个键，再搭配置树（EntryGroup 需要能取到 loader）
        Service.__init__(self, ctx, options)
        EntryTree.__init__(self, ctx)

        if options.get("base_url"):
            self.ctx.base_url = options["base_url"]
        self.ctx.base_url = self.ctx.base_url or str(Path.cwd())

        self._install_hooks()
        ctx.plugin(isolate)

        source = options.get("config")
        if source:
            self.load(source)

    # ------------------------------------------------------------------ 钩子
    def _install_hooks(self) -> None:
        root = self.ctx.root

        # 1. 插件自己改了配置（fiber.update）→ 回写到条目并持久化
        def persist(fiber: Any, config: Any, no_save: bool, next_: Any) -> Any:
            entry = getattr(fiber, "entry", None)
            parent_entry = getattr(fiber.parent.fiber, "entry", None)
            if entry is None or no_save or parent_entry is entry:
                return next_()
            entry.write_config(config)
            return next_()

        root.on("internal/update", persist, global_=True, prepend=True)

        # 2. 记录一次“因配置变更而重载”
        def log_reload(fiber: Any, config: Any, no_save: bool, next_: Any) -> Any:
            entry = getattr(fiber, "entry", None)
            parent_entry = getattr(fiber.parent.fiber, "entry", None)
            if entry is not None and parent_entry is not entry:
                self.show_log(entry, "reload")
            return next_()

        root.on("internal/update", log_reload, global_=True)

        # 3. 把 fiber 与 entry 关联起来，并处理“插件自我卸载”
        def on_plugin(fiber: Any) -> None:
            parent_entry = fiber.parent._own.get(ENTRY_KEY)
            if parent_entry is not None and getattr(fiber, "entry", None) is None:
                fiber.entry = parent_entry
                inject_spec = parent_entry.options.get("inject")
                if inject_spec:
                    fiber.inject.update(
                        {k: None for k in inject_spec}
                        if isinstance(inject_spec, (list, tuple))
                        else dict(inject_spec)
                    )
            self._handle_self_dispose(fiber)

        root.on("internal/plugin", on_plugin, global_=True)

    def _handle_self_dispose(self, fiber: Any) -> None:
        """插件自己调 ``ctx.fiber.dispose()`` 时，把 disabled 写回配置。

        上游在这里区分了六种情况（见 ``loader/src/index.ts`` 的注释），核心目的
        是只处理“用户主动卸载”，不把框架内部的销毁误判成用户意图。这里保留同样
        的判定顺序。
        """
        if fiber.uid:  # case 1: 刚创建
            return
        entry = getattr(fiber, "entry", None)
        if entry is None:  # case 2: 不受 loader 管理
            return
        parent_fiber = getattr(fiber.parent, "fiber", None)
        if parent_fiber is not None and getattr(parent_fiber, "entry", None) is entry:
            return  # case 3: 条目内部的子插件
        if fiber.runtime is None:
            return
        if not self.ctx.registry.has(fiber.runtime.callback):
            return  # case 4: 由 registry.delete 触发（HMR / 删除插件）
        tree = entry.parent.tree
        if not tree.ctx.fiber.uid:  # case 5: 整棵树正在销毁
            return
        self.show_log(entry, "unload")
        if getattr(entry, "options", {}).get("disabled"):
            return  # case 6: loader 自身行为导致的销毁
        entry.options["disabled"] = True
        tree.write()

    # ------------------------------------------------------------------ 配置
    def load(self, source: str | Path | list[dict[str, Any]]) -> None:
        """从文件（或现成的列表）加载配置并应用到根分组。"""
        if isinstance(source, (list, tuple)):
            self._source = None
            entries = normalize(source)
        else:
            path = Path(source)
            self._source = path
            entries = load_config_file(path)
        self.root.update(entries)

    def reload(self) -> None:
        """重新读取配置文件（HMR 用它响应配置文件的改动）。"""
        if self._source is None:
            return
        self.root.update(load_config_file(self._source))

    def write(self) -> None:
        """根树是内存态，写入为空操作（与上游一致）。"""
        return None

    # ------------------------------------------------------------------ 工具
    def show_log(self, entry: Entry, action: str) -> None:
        if entry.options.get("group") or not self.enable_logs:
            return
        self.ctx.root.logger.info("%s plugin %s", action, entry.options.get("name"))

    def locate(self, fiber: Any = None) -> str | None:
        """顺着 fiber 链找到它属于哪个条目。"""
        current = fiber if fiber is not None else self.ctx.fiber
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            entry = getattr(current, "entry", None)
            if entry is not None:
                return entry.id
            parent_fiber = getattr(current.parent, "fiber", None)
            if parent_fiber is current:
                return None
            current = parent_fiber
        return None

    @staticmethod
    def unwrap_exports(exports: Any) -> Any:
        """从模块 / 命名空间里取出真正的插件对象。"""
        return unwrap_exports(exports)

    @staticmethod
    def interpolate(value: Any) -> Any:
        return interpolate(value)


__all__ = [
    "ENTRY_KEY",
    "ConfigError",
    "Entry",
    "EntryGroup",
    "EntryTree",
    "Group",
    "Loader",
    "find_config_file",
    "load_config_file",
    "isolate",
    "unwrap_exports",
]

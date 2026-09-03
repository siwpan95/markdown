"""模块热替换（HMR）。

对应上游 ``@cordisjs/plugin-hmr``。

改一个插件的源码 → 它（以及依赖它的插件）在**不重启进程**的前提下被替换：
旧 Fiber 逆序清理全部副作用，新代码以同样的配置重新加载，其余插件的状态
原封不动。

流程与上游一致，分四步：

1. **监听**：发现文件变化，攒够一个防抖窗口；
2. **分析**：把变化的模块及其**下游依赖者**标记成 accepted，其余标记 declined；
3. **重载**：先 ``registry.delete`` 旧插件，再 ``importlib.reload`` 模块、
   重新注册新插件对象，并用旧 Fiber 的配置复原；
4. **回滚**：任一步失败就退回旧插件对象，保证应用始终处于可用状态。

与上游的三处差异：

* **监听用轮询而不是 chokidar。** 本机没有 watchdog，而且项目里 ``auto-reload``
  插件本来就是轮询 mtime 的，保持一致、零新依赖。代价是最长一个轮询周期的延迟。
* **回调通过宿主提供的 ``schedule`` 切回主线程。** Tkinter 只能在主线程碰控件，
  所以监听线程不直接改应用，而是交给 ``schedule(delay_ms, callback)``
  （在 mdviewer 里就是 ``window.after``）。不传则直接在监听线程里跑。
* **依赖图是“近似”的。** Python 没有 ESM 的 ``ModuleJob.linked``，这里用
  ``module.__dict__`` 里出现过的模块对象来推断依赖，覆盖常规 import 写法；
  动态导入（``importlib.import_module`` 在函数体内）识别不到，属已知边界。
"""

from __future__ import annotations

import dis
import importlib
import sys
import threading
import time
import traceback
import warnings
from pathlib import Path, PurePath
from types import CodeType
from typing import Any, Callable

from .service import Service

#: 事件名
HM_CHANGE = "hmr/change"
HM_RELOAD = "hmr/reload"


def is_excluded(name: str) -> bool:
    """标准库与第三方包不参与热替换。"""
    return name.startswith(("__", "_")) or name in sys.stdlib_module_names


class Hmr(Service):
    """``ctx.hmr`` —— 模块热替换。"""

    name = "hmr"
    #: loader 是**可选**依赖：不走 loader 时 HMR 也能用，只是少了解析配置条目
    #: 那条路径（退化为扫描 registry 反查插件模块）。
    inject: list[str] = []

    def __init__(self, ctx: Any, config: Any = None) -> None:
        super().__init__(ctx, config)
        options = self.config if isinstance(self.config, dict) else {}
        self.base_dir = Path(options.get("base") or ctx.base_url or ".").resolve()
        self.roots: list[str] = list(options.get("root") or ["."])
        self.ignored: list[str] = list(
            options.get("ignored") or ["**/.*", "**/__pycache__", "**/node_modules"]
        )
        self.debounce: int = int(options.get("debounce") or 200)
        self.poll_interval: float = float(options.get("poll_interval") or 200) / 1000
        #: 宿主提供的调度器，用于切回主线程（Tkinter 场景必需）
        self.schedule: Callable[[int, Callable[[], Any]], Any] | None = options.get(
            "schedule"
        )

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._stashed: set[str] = set()
        self._timer: Any = None
        self._lock = threading.Lock()
        self._mtimes: dict[str, float] = {}
        self._import_cache: dict[tuple[str, float], set[str]] = {}
        self.reload_count = 0
        self.last_error: BaseException | None = None

    # ------------------------------------------------------------------ 监听
    def init(self) -> None:
        self.ctx.logger.info("hmr: watching %s", self.base_dir)
        # 先同步扫一遍建立 mtime 基线，再起线程。
        # 否则「刚启动就改文件」会撞上竞态：首轮基线取到的是改后的时间，
        # 那次改动就永远检测不到。
        self._scan()
        self._thread = threading.Thread(target=self._poll, name="cordis-hmr", daemon=True)
        self._thread.start()
        # 注意：ctx.effect(fn) 会**执行** fn 并收集它的返回值，所以这里要写成
        # ``lambda: self.stop``（返回绑定方法）而不是 ``self.stop``
        self.ctx.effect(lambda: self.stop, "hmr:thread")

    def stop(self) -> None:
        """停止监听线程。"""
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _iter_files(self):
        seen: set[Path] = set()
        for root in self.roots:
            base = (self.base_dir / root).resolve()
            if base.is_file():
                candidates = [base]
            else:
                candidates = sorted(base.rglob("*.py"))
            for path in candidates:
                if path in seen:
                    continue
                seen.add(path)
                rel = self._relative(path)
                if rel is None or self._is_ignored(rel):
                    continue
                yield path

    def _relative(self, path: Path) -> str | None:
        try:
            return str(path.relative_to(self.base_dir)).replace("\\", "/")
        except ValueError:
            return None

    def _is_ignored(self, rel: str) -> bool:
        """按路径段匹配忽略规则。

        不用 :func:`fnmatch.fnmatch`：它的 ``*`` 会跨 ``/`` 匹配，导致
        ``**/.*`` 误伤所有“斜杠后面带点”的普通文件（如 ``mdviewer/plugins/toc.py``）。
        :meth:`PurePath.match` 按 ``/`` 分段匹配，``**`` 只吞目录，语义与
        chokidar 的 glob 一致。
        """
        path = PurePath(rel)
        return any(path.match(pattern) for pattern in self.ignored)

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan()
            except Exception:  # noqa: BLE001 - 监听线程不能因为一次异常就退出
                traceback.print_exc()
            self._stop.wait(self.poll_interval)

    def _scan(self) -> None:
        changed: set[str] = set()
        for path in self._iter_files():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            key = str(path)
            old = self._mtimes.get(key)
            self._mtimes[key] = mtime
            if old is not None and mtime > old:
                changed.add(key)
        if not changed or not self._mtimes:
            return
        # 首轮只登记 mtime，不算变化
        if any(k not in self._mtimes for k in changed):
            return
        with self._lock:
            self._stashed |= changed
        self._kick()

    def _kick(self) -> None:
        """防抖：攒够窗口再真正重载。"""
        if self.schedule is None:
            self._debounced_reload()
            return
        # schedule 只能由宿主线程调用；这里直接排一次即可（幂等由 _timer 保证）
        self._timer = self.schedule(self.debounce, self._debounced_reload)

    def _debounced_reload(self) -> None:
        with self._lock:
            stashed = set(self._stashed)
            self._stashed.clear()
        if not stashed:
            return
        for filename in stashed:
            self.ctx.emit(HM_CHANGE, filename)
        try:
            reloads = self.partial_reload(stashed)
        except Exception as error:  # noqa: BLE001
            self.last_error = error
            self.ctx.logger.error(error)
            return
        # last_error 反映“最近一次”重载的结果，成功后要清掉，
        # 否则一次失败修好之后，外部仍会读到旧的异常
        self.last_error = None
        if reloads:
            self.reload_count += 1
            self.ctx.emit(HM_RELOAD, reloads)

    # ------------------------------------------------------------------ 依赖图
    def module_imports(self, module: Any) -> set[str]:
        """从源码字节码里提取 ``IMPORT_NAME`` / ``IMPORT_FROM``，得到导入的模块名。

        Python 不暴露 ESM 那样的 ``ModuleJob.linked`` 依赖图，而且
        ``from x import y`` 在模块命名空间里只留下 ``y``（一个值，不是模块），
        光看 ``vars(module)`` 是找不出 ``x`` 的。所以这里直接读字节码——
        编译一次即可，结果按 (文件, mtime) 缓存。

        识别不到的边界：函数体内的动态 ``importlib.import_module(...)``。
        """
        source_file = getattr(module, "__file__", None)
        if not source_file:
            return set()
        path = Path(source_file)
        try:
            mtime = path.stat().st_mtime
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return set()

        cache_key = (str(path.resolve()), mtime)
        cached = self._import_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # 静默编译：只取 import 名，不需要第三方库的 SyntaxWarning /
            # DeprecationWarning 刷屏（例如 traitlets 的 `len(key) is 1`）
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                top = compile(source, str(path), "exec")
        except SyntaxError:
            return set()

        names: set[str] = set()
        last_import: str | None = None
        stack = [top]
        while stack:
            code = stack.pop()
            for instruction in dis.get_instructions(code):
                if instruction.opname == "IMPORT_NAME":
                    last_import = instruction.argval
                    names.add(instruction.argval)
                elif instruction.opname == "IMPORT_FROM" and last_import:
                    names.add(f"{last_import}.{instruction.argval}")
            for const in code.co_consts:
                if isinstance(const, CodeType):
                    stack.append(const)

        self._import_cache[cache_key] = names
        return names

    def _resolve_import(self, name: str) -> Any:
        """把导入名解析成已加载的模块。"""
        module = sys.modules.get(name)
        if module is not None:
            return module
        if "." in name:
            head, _, tail = name.partition(".")
            parent = sys.modules.get(head)
            if parent is None:
                return None
            current: Any = parent
            for part in tail.split("."):
                current = getattr(current, part, None)
                if current is None:
                    return None
            return current if isinstance(current, type(sys)) else None
        return None

    def module_dependencies(self, module: Any, ignored: set[str] | None = None) -> set[str]:
        """收集一个模块（递归）依赖的本地文件。"""
        ignored = set(ignored or ())
        result: set[str] = set()
        stack = [module]
        seen: set[int] = set()
        while stack:
            current = stack.pop()
            if current is None or not hasattr(current, "__dict__"):
                continue
            if id(current) in seen:
                continue
            seen.add(id(current))

            candidates: list[Any] = []
            # 1) 字节码里的 import
            for name in self.module_imports(current):
                if is_excluded(name.split(".")[0]):
                    continue
                resolved = self._resolve_import(name)
                if resolved is not None:
                    candidates.append(resolved)
            # 2) 命名空间里的模块对象（覆盖动态导入 / 运行时注入）
            candidates += [
                value
                for value in list(vars(current).values())
                if isinstance(value, type(sys))
            ]

            for dependency in candidates:
                name = getattr(dependency, "__name__", "")
                if is_excluded(name.split(".")[0]):
                    continue
                source = getattr(dependency, "__file__", None)
                if not source:
                    continue
                key = str(Path(source).resolve())
                if key in result:
                    continue
                # 直接依赖要记进结果；``ignored`` 只用来截断**更深**的遍历
                result.add(key)
                if key not in ignored:
                    stack.append(dependency)
        return result

    def _dependents(self, filename: str) -> set[str]:
        """谁（直接或间接）依赖了这个文件。

        只扫描 base_dir 下的模块：要重载的模块本来就限定在项目内，
        依赖者自然也是项目内的，这样能把第三方库（tkinter 全家、traitlets
        等）从编译成本里剔除。
        """
        target = str(Path(filename).resolve())
        base = str(self.base_dir)
        affected: set[str] = {target}
        changed = True
        while changed:
            changed = False
            for name, module in list(sys.modules.items()):
                if module is None or is_excluded(name.split(".")[0]):
                    continue
                source = getattr(module, "__file__", None)
                if not source:
                    continue
                key = str(Path(source).resolve())
                if key in affected or not key.startswith(base):
                    continue
                if target in self.module_dependencies(module, ignored=affected):
                    affected.add(key)
                    changed = True
        return affected

    # ------------------------------------------------------------------ 模块
    @staticmethod
    def _reload_module(module: Any) -> Any:
        """原地重新执行一个模块。

        ``importlib.reload`` 要求模块能按名字再次 ``find_spec``，而 loader 按文件
        路径导入的插件用的是合成模块名（``cordis._loaded_<hash>``），这个名字
        查不到，reload 会报 ``spec not found``。因此这里直接拿 ``__spec__`` 上的
        loader 重新 ``exec_module`` —— 效果等价，且不依赖模块名可导入。
        """
        spec = getattr(module, "__spec__", None)
        if spec is not None and getattr(spec, "loader", None) is not None:
            spec.loader.exec_module(module)
            return module
        return importlib.reload(module)

    def _ordered(self, modules: list[Any]) -> list[Any]:
        """按依赖顺序排序：**被依赖的先重载**。

        有环时（互相 import）放弃拓扑，按原顺序追加，避免死循环。
        """
        # 同一个模块可能既在“受影响的模块”里、又是插件入口，去重后再排
        unique: list[Any] = []
        seen: set[int] = set()
        for module in modules:
            if id(module) in seen:
                continue
            seen.add(id(module))
            unique.append(module)

        remaining = list(unique)
        result: list[Any] = []
        while remaining:
            progressed = False
            for module in list(remaining):
                own = str(Path(getattr(module, "__file__", "") or "").resolve())
                others = {
                    str(Path(getattr(m, "__file__", "") or "").resolve())
                    for m in remaining
                    if m is not module
                }
                if self.module_dependencies(module) & others:
                    continue
                result.append(module)
                remaining.remove(module)
                progressed = True
            if not progressed:
                result.extend(remaining)
                break
        return result

    # ------------------------------------------------------------------ 重载
    def _unwrap(self, exports: Any) -> Any:
        """把模块/命名空间还原成插件对象（loader 不存在时退回静态实现）。"""
        loader = self.ctx.get("loader")
        if loader is not None:
            return loader.unwrap_exports(exports)
        from .loader.tree import unwrap_exports

        return unwrap_exports(exports)

    def partial_reload(self, changed: set[str]) -> dict[Any, dict[str, Any]]:
        """重载受影响的插件，返回 ``{旧插件对象: {filename, fibers}}``。"""
        accepted: set[str] = set()
        for filename in changed:
            accepted |= self._dependents(filename)

        loader = self.ctx.get("loader")
        base = str(self.base_dir)

        # 1) 需要重载的**所有**模块：既包括插件入口，也包括被依赖的普通模块。
        #    上游靠清空 ESM 模块缓存让依赖链自然重新加载；Python 侧要显式做，
        #    否则插件重载后拿到的还是旧依赖。只处理 base_dir 下的文件。
        affected_modules: list[Any] = []
        seen: set[int] = set()
        for name, module in list(sys.modules.items()):
            if module is None or is_excluded(name.split(".")[0]):
                continue
            source = getattr(module, "__file__", None)
            if not source:
                continue
            resolved = str(Path(source).resolve())
            if resolved not in accepted or not resolved.startswith(base):
                continue
            if id(module) in seen:
                continue
            seen.add(id(module))
            affected_modules.append(module)

        # 2) 插件入口模块（用于重新注册）
        candidates: dict[str, Any] = {}
        if loader is not None:
            for key, module in list(getattr(loader, "modules", {}).items()):
                source = getattr(module, "__file__", None)
                if source and str(Path(source).resolve()) in accepted:
                    candidates[key] = module
            for entry in loader.entries():
                name = str(entry.options.get("name") or "")
                if name in candidates or name.startswith("cordis:"):
                    continue
                module = sys.modules.get(name)
                if module is None:
                    continue
                source = getattr(module, "__file__", None)
                if source and str(Path(source).resolve()) in accepted:
                    candidates[name] = module

        # 兜底：不走 loader、直接在代码里 ctx.plugin(...) 注册的插件也要能被热替换，
        # 这里按 registry 里的 callback 反查它所属的模块文件。
        for runtime in self.ctx.registry.values():
            callback = runtime.callback
            module_name = getattr(callback, "__module__", None)
            if not module_name:
                continue
            module = sys.modules.get(module_name)
            if module is None:
                continue
            source = getattr(module, "__file__", None)
            if source and str(Path(source).resolve()) in accepted:
                candidates.setdefault(module_name, module)

        if not candidates:
            return {}

        # 快照：runtime → 该插件所有 fiber 的 (父上下文, 配置)
        plan: list[tuple[Any, Any, list[tuple[Any, Any]]]] = []
        for module in candidates.values():
            plugin = self._unwrap(module)
            if plugin is None:
                continue
            runtime = self.ctx.registry.get(plugin)
            if runtime is None:
                continue
            snapshot = [
                (f.parent, f.config, getattr(f, "entry", None))
                for f in list(runtime.fibers)
            ]
            plan.append((module, plugin, snapshot))

        reloads: dict[Any, dict[str, Any]] = {}
        for module, plugin, snapshot in plan:
            reloads[plugin] = {
                "filename": getattr(module, "__file__", ""),
                "fibers": snapshot,
            }

        # 1) 卸载旧插件（副作用按 Cordis 的规矩逆序清理）
        for _module, plugin, _snapshot in plan:
            self.ctx.registry.delete(plugin)

        # 2) 重新加载模块（被依赖的先重载）
        reloaded: dict[str, Any] = {}
        try:
            for module in self._ordered(affected_modules + list(candidates.values())):
                reloaded[module.__name__] = self._reload_module(module)
        except Exception as error:  # noqa: BLE001
            self.last_error = error
            self._rollback(plan, reloaded)
            raise

        # 3) 用同样的配置重新注册
        try:
            for _module, _plugin, snapshot in plan:
                module = reloaded.get(_module.__name__, _module)
                new_plugin = self._unwrap(module)
                if new_plugin is None:
                    raise RuntimeError(f"{_module.__name__} 重载后找不到插件对象")
                for parent_ctx, config, entry in snapshot:
                    fiber = parent_ctx.plugin(new_plugin, config)
                    # 新 Fiber 要接手旧 Fiber 的配置条目，否则 loader 之后
                    # 再更新这条配置时会操作到一个已经销毁的 Fiber 上
                    if entry is not None:
                        fiber.entry = entry
                        entry.fiber = fiber
        except Exception as error:  # noqa: BLE001
            self.last_error = error
            self._rollback(plan, reloaded)
            raise

        for _module, plugin, _snapshot in plan:
            path = _module.__file__ or ""
            try:
                rel = str(Path(path).relative_to(self.base_dir))
            except ValueError:
                rel = path
            self.ctx.logger.info("hmr: reloaded %s", rel)
        return reloads

    def _rollback(self, plan: list[tuple[Any, Any, list[tuple[Any, Any]]]], reloaded: dict[str, Any]) -> None:
        """回滚：清掉新注册的，把旧插件对象按原配置装回去。"""
        self.ctx.logger.warn("hmr: 重载失败，正在回滚")
        for name, module in reloaded.items():
            try:
                plugin = self._unwrap(module)
                if plugin is not None and self.ctx.registry.has(plugin):
                    self.ctx.registry.delete(plugin)
            except Exception:  # noqa: BLE001
                pass
        for _module, plugin, snapshot in plan:
            try:
                for parent_ctx, config, entry in snapshot:
                    fiber = parent_ctx.plugin(plugin, config)
                    if entry is not None:
                        fiber.entry = entry
                        entry.fiber = fiber
            except Exception as error:  # noqa: BLE001
                self.ctx.logger.error(error)

    # ------------------------------------------------------------------ 手动
    def reload_plugin(self, plugin: Any) -> bool:
        """手动触发某个插件的热替换（测试与调试用）。"""
        runtime = self.ctx.registry.get(plugin)
        if runtime is None:
            return False
        module = sys.modules.get(getattr(plugin, "__module__", ""))
        if module is None or not getattr(module, "__file__", None):
            return False
        return bool(self.partial_reload({module.__file__}))


__all__ = ["HM_CHANGE", "HM_RELOAD", "Hmr", "is_excluded"]

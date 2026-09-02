"""Cordis —— 时空可组合性元框架的 Python 移植。

本包是 ``G:\\local\\markdown\\cordis-main``（TypeScript 版 ``@cordisjs/core``）
的 Python 实现，用于驱动本地 Markdown 查看器的插件化重构。

核心概念（与上游一一对应）::

    Context   服务容器 / 插件作用域，可 extend、isolate、intercept
    Fiber     一次插件加载的执行域，管生命周期与副作用栈
    Service   占据稳定上下文键的对象，卸载时自动释放
    effect    可逆副作用：注册即返回 disposer，卸载时逆序调用
    inject    声明式依赖：依赖未就绪则插件不启动，依赖消失则自动停用
    events    emit / serial / bail / parallel / waterfall 五种分发

最小示例::

    from cordis import Context, Service

    class Counter(Service):
        name = "counter"
        def __init__(self, ctx, config=None):
            super().__init__(ctx, config)
            self.value = 0

    def apply(ctx, config):
        # 声明依赖，Cordis 保证进入这里时 ctx.counter 一定可用
        ctx.on("tick", lambda n: setattr(ctx.counter, "value", ctx.counter.value + n))
        return lambda: print("插件已卸载，监听器自动移除")

    apply.inject = ["counter"]

    ctx = Context()
    ctx.plugin(Counter)
    ctx.plugin(apply)
    ctx.emit("tick", 3)
    assert ctx.counter.value == 3
    ctx.registry.delete(apply)          # 卸载插件
    ctx.emit("tick", 3)                 # 监听器已消失
    assert ctx.counter.value == 3

与上游的已知差异记录在 ``context.py`` / ``events.py`` / ``fiber.py`` / ``reflect.py``
的模块注释里，主要是「无 Proxy」「无 this 绑定」「同步而非异步」三点。
"""

from .context import Context
from .events import EventsService, Hook
from .fiber import EffectMeta, Fiber, FiberState
from .logger import Logger, LoggerService
from .reflect import Impl, Property, ReflectService
from .registry import InjectSpec, RegistryService, Runtime, inject
from .service import Service
from .utils import CordisError, DisposableList, Symbol, symbols

__all__ = [
    "Context",
    "CordisError",
    "DisposableList",
    "EffectMeta",
    "EventsService",
    "Fiber",
    "FiberState",
    "Hook",
    "Impl",
    "InjectSpec",
    "Logger",
    "LoggerService",
    "Property",
    "ReflectService",
    "RegistryService",
    "Runtime",
    "Service",
    "Symbol",
    "inject",
    "symbols",
]

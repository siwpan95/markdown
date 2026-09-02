"""Cordis 运行时的单元测试。

不依赖 Tkinter，可以独立运行::

    python -m unittest tests.test_cordis -v

用例围绕两条主线：**时间可组合性**（副作用可逆）与**空间可组合性**
（依赖可声明），外加事件分发与上下文派生的行为。
"""

from __future__ import annotations

import logging
import unittest

from cordis import Context, CordisError, FiberState, Service, inject

# 预期内的错误（如 test_failed_plugin_does_not_crash）会走 logger，
# 这里挂一个空 handler，避免污染测试输出。
logging.getLogger("cordis").addHandler(logging.NullHandler())


class Counter(Service):
    """一个最简单的服务，用于验证依赖等待。"""

    name = "counter"

    def __init__(self, ctx, config=None):
        super().__init__(ctx, config)
        self.value = 0


class TestEffect(unittest.TestCase):
    """副作用的可逆性。"""

    def test_disposer_called_on_unload(self):
        log = []
        ctx = Context()

        def apply(ctx, config):
            ctx.on("ping", lambda: log.append("ping"))
            return lambda: log.append("dispose")

        fiber = ctx.plugin(apply)
        ctx.emit("ping")
        fiber.dispose()
        ctx.emit("ping")
        self.assertEqual(log, ["ping", "dispose"])
        self.assertEqual(fiber.state, FiberState.DISPOSED)

    def test_effect_return_forms(self):
        """disposer 可以是函数、生成器或列表。"""
        log = []
        ctx = Context()

        def apply(ctx, config):
            ctx.effect(lambda: log.append("a") and None or (lambda: log.append("-a")))
            return None

        fiber = ctx.plugin(apply)
        fiber.dispose()
        self.assertIn("-a", log)

    def test_generator_effect(self):
        log = []
        ctx = Context()

        def apply(ctx, config):
            def body():
                yield lambda: log.append("clean-2")
                yield lambda: log.append("clean-1")

            ctx.effect(body, "generator")

        fiber = ctx.plugin(apply)
        fiber.dispose()
        # 逆序清理：后注册的先撤销
        self.assertEqual(log, ["clean-1", "clean-2"])

    def test_reverse_order(self):
        log = []
        ctx = Context()

        def apply(ctx, config):
            ctx.effect(lambda: (log.append("1"), lambda: log.append("undo-1"))[1], "one")
            ctx.effect(lambda: (log.append("2"), lambda: log.append("undo-2"))[1], "two")

        fiber = ctx.plugin(apply)
        fiber.dispose()
        self.assertEqual(log, ["1", "2", "undo-2", "undo-1"])

    def test_invalid_effect_rejected(self):
        """非可调用的返回值必须报错，而不是被静默忽略。"""
        ctx = Context()

        def apply(ctx, config):
            ctx.effect(lambda: 42, "bad")

        fiber = ctx.plugin(apply)
        self.assertEqual(fiber.state, FiberState.FAILED)

    def test_effect_on_inactive_context(self):
        ctx = Context()
        seen = {}

        def apply(ctx, config):
            seen["ctx"] = ctx
            return None

        fiber = ctx.plugin(apply)
        fiber.dispose()
        with self.assertRaises(CordisError):
            seen["ctx"].effect(lambda: None)


class TestInject(unittest.TestCase):
    """依赖声明与响应式加载。"""

    def test_pending_until_service_ready(self):
        log = []
        ctx = Context()

        def watcher(ctx, config):
            log.append(f"load:{ctx.counter}")
            return lambda: log.append("unload")

        watcher.inject = ["counter"]
        fiber = ctx.plugin(watcher)
        self.assertEqual(fiber.state, FiberState.PENDING)
        self.assertEqual(log, [])

        ctx.plugin(Counter)
        self.assertEqual(fiber.state, FiberState.ACTIVE)
        self.assertEqual(log, ["load:" + repr(ctx.counter)])

    def test_unload_when_service_disappears(self):
        log = []
        ctx = Context()

        def watcher(ctx, config):
            ctx.on("ping", lambda: log.append("ping"))
            return lambda: log.append("unload")

        watcher.inject = ["counter"]
        fiber = ctx.plugin(watcher)
        ctx.plugin(Counter)
        ctx.emit("ping")

        ctx.registry.delete(Counter)
        self.assertEqual(fiber.state, FiberState.PENDING)
        ctx.emit("ping")
        # 停用后监听器已被移除
        self.assertEqual(log, ["ping", "unload"])

    def test_access_without_inject_raises(self):
        ctx = Context()
        ctx.plugin(Counter)
        errors = []

        def sneaky(ctx, config):
            try:
                ctx.counter
            except CordisError as error:
                errors.append(error.code)

        ctx.plugin(sneaky)
        self.assertEqual(errors, ["UNINJECTED_PROPERTY"])

    def test_inject_decorator(self):
        ctx = Context()
        ctx.plugin(Counter)

        @inject("counter")
        def apply(ctx, config):
            ctx.counter.value = 7

        fiber = ctx.plugin(apply)
        self.assertEqual(fiber.state, FiberState.ACTIVE)
        self.assertEqual(ctx.counter.value, 7)

    def test_ctx_inject_helper(self):
        """``ctx.inject`` 会一直等到依赖就绪。"""
        seen = []
        ctx = Context()
        ctx.inject(["counter"], lambda c: seen.append(c.counter))
        self.assertEqual(seen, [])
        ctx.plugin(Counter)
        self.assertEqual(len(seen), 1)

    def test_class_inject_inheritance(self):
        class Base(Service):
            name = "derived"
            inject = ["counter"]

        class Child(Base):
            inject = ["counter", "counter"]

        ctx = Context()
        ctx.plugin(Counter)
        fiber = ctx.plugin(Child)
        self.assertEqual(fiber.state, FiberState.ACTIVE)
        self.assertIn("counter", fiber.inject)


class TestEvents(unittest.TestCase):
    """五种分发模式。"""

    def test_emit_broadcast(self):
        ctx = Context()
        hits = []
        ctx.on("go", lambda v: hits.append(("a", v)))
        ctx.on("go", lambda v: hits.append(("b", v)))
        ctx.emit("go", 1)
        self.assertEqual(hits, [("a", 1), ("b", 1)])

    def test_serial_short_circuits(self):
        ctx = Context()
        ctx.on("pick", lambda v: None)
        ctx.on("pick", lambda v: f"chosen:{v}")
        ctx.on("pick", lambda v: "never")
        self.assertEqual(ctx.serial("pick", 7), "chosen:7")

    def test_waterfall_onion(self):
        ctx = Context()
        order = []
        ctx.on("save", lambda cfg, next: (order.append("A-in"), next(), order.append("A-out")))
        ctx.on("save", lambda cfg, next: (order.append("B-in"), next(), order.append("B-out")))
        ctx.waterfall("save", {"x": 1}, lambda cfg: order.append("commit"))
        self.assertEqual(order, ["A-in", "B-in", "commit", "B-out", "A-out"])

    def test_waterfall_can_reject(self):
        ctx = Context()
        ctx.on("save", lambda cfg, next: "denied")
        ctx.on("save", lambda cfg, next: "never")
        self.assertEqual(ctx.waterfall("save", {}, lambda: "commit"), "denied")

    def test_once(self):
        ctx = Context()
        hits = []
        ctx.once("boom", lambda v: hits.append(v))
        ctx.emit("boom", 1)
        ctx.emit("boom", 2)
        self.assertEqual(hits, [1])

    def test_prepend(self):
        ctx = Context()
        order = []
        ctx.on("go", lambda: order.append("second"))
        ctx.on("go", lambda: order.append("first"), prepend=True)
        ctx.emit("go")
        self.assertEqual(order, ["first", "second"])

    def test_parallel_aggregates_errors(self):
        ctx = Context()
        ctx.on("risky", lambda: (_ for _ in ()).throw(ValueError("x")))
        ctx.on("risky", lambda: (_ for _ in ()).throw(ValueError("y")))
        with self.assertRaises(ExceptionGroup) as caught:
            ctx.parallel("risky")
        self.assertEqual(len(caught.exception.exceptions), 2)


class TestContext(unittest.TestCase):
    """上下文派生与隔离。"""

    def test_extend_shares_services(self):
        ctx = Context()
        ctx.plugin(Counter)
        child = ctx.extend({"tag": "x"})
        self.assertEqual(child.tag, "x")
        self.assertIs(child.counter, ctx.counter)

    def test_isolate_hides_service(self):
        ctx = Context()
        ctx.plugin(Counter)
        isolated = ctx.isolate("counter")
        self.assertIsNotNone(ctx.get("counter"))
        self.assertIsNone(isolated.get("counter"))

    def test_isolate_scoped_registration(self):
        ctx = Context()
        scoped = ctx.isolate("counter")
        scoped.plugin(Counter)
        self.assertIsNone(ctx.get("counter"))
        self.assertIsNotNone(scoped.get("counter"))

    def test_duplicate_service_rejected(self):
        """同一个上下文里重复 provide 同名服务会失败（Fiber 进入 FAILED）。"""
        ctx = Context()
        ctx.plugin(Counter)
        # 同一个插件可以有多份实例，但第二份抢不到服务名
        second = ctx.plugin(Counter)
        self.assertEqual(second.state, FiberState.FAILED)

    def test_duplicate_provide_raises(self):
        ctx = Context()
        ctx.plugin(Counter)
        with self.assertRaises(CordisError):
            ctx.provide("counter", Counter(ctx, "counter"))

    def test_set_without_provide_rejected(self):
        ctx = Context()

        def apply(ctx, config):
            ctx.something = 1

        fiber = ctx.plugin(apply)
        self.assertEqual(fiber.state, FiberState.FAILED)


class TestLifecycle(unittest.TestCase):
    """配置热更新与嵌套插件。"""

    def test_update_restarts_plugin(self):
        log = []
        ctx = Context()

        def apply(ctx, config):
            log.append(f"load:{config}")
            return lambda: log.append(f"unload:{config}")

        fiber = ctx.plugin(apply, {"a": 1})
        fiber.update({"a": 2})
        self.assertEqual(log, ["load:{'a': 1}", "unload:{'a': 1}", "load:{'a': 2}"])

    def test_nested_plugin_disposal(self):
        log = []
        ctx = Context()

        def outer(ctx, config):
            log.append("outer+")
            ctx.plugin(inner)
            return lambda: log.append("outer-")

        def inner(ctx, config):
            log.append("inner+")
            return lambda: log.append("inner-")

        outer.name = "outer"
        inner.name = "inner"
        fiber = ctx.plugin(outer)
        fiber.dispose()
        self.assertEqual(log, ["outer+", "inner+", "outer-", "inner-"])

    def test_failed_plugin_does_not_crash(self):
        ctx = Context()

        def boom(ctx, config):
            raise RuntimeError("boom")

        fiber = ctx.plugin(boom)
        self.assertEqual(fiber.state, FiberState.FAILED)

    def test_registry_size(self):
        ctx = Context()
        ctx.plugin(Counter)
        self.assertEqual(ctx.registry.size, 1)
        ctx.registry.delete(Counter)
        self.assertEqual(ctx.registry.size, 0)


if __name__ == "__main__":
    unittest.main()

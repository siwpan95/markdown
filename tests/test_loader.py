"""Cordis loader / HMR 的测试。

对应上游 ``packages/loader/tests`` 与 ``packages/hmr/tests`` 覆盖的语义，
外加本项目特有的两种宿主场景（Tk 窗口下的声明式装配、主线程热替换）。

运行::

    python -m unittest tests.test_loader -v
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from cordis import Context
from cordis.hmr import Hmr
from cordis.loader import Entry, Group, Loader
from cordis.loader.config import ConfigError, load_config_file, normalize

PROJECT_ROOT = Path(__file__).resolve().parent.parent
logging.getLogger("cordis").addHandler(logging.NullHandler())


def make_plugin(log):
    """生成一个会把自己加载/卸载记录进 ``log`` 的插件函数。"""

    def apply(ctx, config=None):
        name = (config or {}).get("name", "?")
        log.append(f"+{name}")
        ctx.on("ping", lambda: log.append(f"!{name}"))
        return lambda: log.append(f"-{name}")

    apply.name = "probe"
    return apply


class LoaderCase(unittest.TestCase):
    def setUp(self) -> None:
        self.log: list[str] = []
        self.ctx = Context()
        self.ctx.plugin(Loader, {"logs": True})
        self.ctx.loader.builtins["probe"] = make_plugin(self.log)

    def load(self, entries) -> None:
        self.ctx.loader.load(entries)

    def ids(self) -> list[str]:
        return [entry.id for entry in self.ctx.loader.entries()]


class TestEntry(LoaderCase):
    def test_load_in_order(self):
        self.load(
            [
                {"id": "a", "name": "cordis:probe", "config": {"name": "A"}},
                {"id": "b", "name": "cordis:probe", "config": {"name": "B"}},
            ]
        )
        self.assertEqual(self.log, ["+A", "+B"])
        self.assertEqual(self.ids(), ["a", "b"])

    def test_config_change_restarts_only_that_entry(self):
        self.load(
            [
                {"id": "a", "name": "cordis:probe", "config": {"name": "A"}},
                {"id": "b", "name": "cordis:probe", "config": {"name": "B"}},
            ]
        )
        self.log.clear()
        self.ctx.loader.update("a", {"config": {"name": "A2"}})
        # 只有 a 被重建，b 的状态原样保留
        self.assertEqual(self.log, ["-A", "+A2"])
        self.log.clear()
        self.ctx.emit("ping")
        self.assertEqual(self.log, ["!B", "!A2"])

    def test_disabled_entry_does_not_load(self):
        self.load(
            [
                {"id": "a", "name": "cordis:probe", "config": {"name": "A"}},
                {
                    "id": "b",
                    "name": "cordis:probe",
                    "config": {"name": "B"},
                    "disabled": True,
                },
            ]
        )
        self.assertEqual(self.log, ["+A"])
        self.assertFalse(self.ctx.loader.resolve("b").fiber)

    def test_toggle_disabled_round_trip(self):
        self.load([{"id": "a", "name": "cordis:probe", "config": {"name": "A"}}])
        self.ctx.loader.update("a", {"disabled": True})
        self.assertEqual(self.log, ["+A", "-A"])
        self.log.clear()
        self.ctx.loader.update("a", {"disabled": False})
        self.assertEqual(self.log, ["+A"])
        self.assertEqual(self.ctx.loader.resolve("a").fiber.state.name, "ACTIVE")

    def test_remove_entry(self):
        self.load([{"id": "a", "name": "cordis:probe", "config": {"name": "A"}}])
        self.ctx.loader.remove("a")
        self.assertEqual(self.log, ["+A", "-A"])
        self.assertEqual(self.ids(), [])

    def test_missing_id_gets_generated(self):
        self.load([{"name": "cordis:probe", "config": {"name": "A"}}])
        generated = self.ids()
        self.assertEqual(len(generated), 1)
        self.assertEqual(len(generated[0]), 8)  # secrets.token_hex(4)

    def test_unknown_builtin_logs_error(self):
        self.ctx.loader.load([{"id": "x", "name": "cordis:nope"}])
        self.assertEqual(self.log, [])


class TestGroup(LoaderCase):
    def test_nested_ids(self):
        self.load(
            [
                {
                    "id": "ui",
                    "name": "cordis:group",
                    "config": [
                        {"id": "find", "name": "cordis:probe", "config": {"name": "F"}},
                        {"id": "toc", "name": "cordis:probe", "config": {"name": "T"}},
                    ],
                }
            ]
        )
        self.assertEqual(self.ids(), ["ui", "ui:find", "ui:toc"])
        self.assertEqual(self.log, ["+F", "+T"])

    def test_group_disabled_propagates(self):
        """分组被禁用时它自己都不加载，子树自然也不会被建出来。"""
        self.load(
            [
                {
                    "id": "ui",
                    "name": "cordis:group",
                    "disabled": True,
                    "config": [
                        {"id": "find", "name": "cordis:probe", "config": {"name": "F"}}
                    ],
                }
            ]
        )
        self.assertEqual(self.log, [])
        self.assertEqual(self.ids(), ["ui"])
        self.assertTrue(self.ctx.loader.resolve("ui").disabled)

    def test_disable_group_unloads_children(self):
        self.load(
            [
                {
                    "id": "ui",
                    "name": "cordis:group",
                    "config": [
                        {"id": "find", "name": "cordis:probe", "config": {"name": "F"}}
                    ],
                }
            ]
        )
        self.assertEqual(self.log, ["+F"])
        self.ctx.loader.update("ui", {"disabled": True})
        # 分组卸载时整棵子树一起停掉
        self.assertEqual(self.log, ["+F", "-F"])
        self.assertEqual(self.ids(), ["ui"])

    def test_group_is_registered_builtin(self):
        self.assertIs(self.ctx.loader.builtins["group"], Group)

    def test_nested_entry_resolvable_by_leaf_id(self):
        self.load(
            [
                {
                    "id": "ui",
                    "name": "cordis:group",
                    "config": [
                        {"id": "find", "name": "cordis:probe", "config": {"name": "F"}}
                    ],
                }
            ]
        )
        self.assertIs(self.ctx.loader.resolve("find"), self.ctx.loader.resolve("ui:find"))


class TestConfigFile(LoaderCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return path

    def test_yaml(self):
        path = self._write(
            "cordis.yml",
            """
            - id: a
              name: cordis:probe
              config:
                name: from-yaml
            """,
        )
        self.ctx.loader.load(path)
        self.assertEqual(self.log, ["+from-yaml"])

    def test_json(self):
        path = self._write(
            "cordis.json",
            """
            [{"id": "a", "name": "cordis:probe", "config": {"name": "from-json"}}]
            """,
        )
        self.ctx.loader.load(path)
        self.assertEqual(self.log, ["+from-json"])

    def test_toml(self):
        path = self._write(
            "cordis.toml",
            """
            [[plugin]]
            id = "a"
            name = "cordis:probe"

            [plugin.config]
            name = "from-toml"
            """,
        )
        self.ctx.loader.load(path)
        self.assertEqual(self.log, ["+from-toml"])

    def test_env_interpolation(self):
        path = self._write(
            "cordis.toml",
            """
            [[plugin]]
            id = "a"
            name = "cordis:probe"

            [plugin.config]
            name = { "$env" = ["MDV_TEST_VAR", "fallback"] }
            """,
        )
        os.environ["MDV_TEST_VAR"] = "from-env"
        try:
            self.ctx.loader.load(path)
        finally:
            os.environ.pop("MDV_TEST_VAR")
        self.assertEqual(self.log, ["+from-env"])

    def test_env_fallback(self):
        path = self._write(
            "cordis.json",
            """
            [{"id": "a", "name": "cordis:probe",
              "config": {"name": {"$env": ["MDV_MISSING_VAR", "fallback"]}}}]
            """,
        )
        self.ctx.loader.load(path)
        self.assertEqual(self.log, ["+fallback"])

    def test_yaml_boolean_id_trap(self):
        """YAML 1.1 把 off 解析成 False —— 必须给出可读的报错而不是静默换 id。"""
        with self.assertRaises(ConfigError) as caught:
            normalize([{"id": False, "name": "x"}])
        self.assertIn("YAML 1.1", str(caught.exception))

    def test_unsupported_suffix(self):
        path = self._write("cordis.ini", "[a]\n")
        with self.assertRaises(ConfigError) as caught:
            load_config_file(path)
        self.assertIn("不支持的配置文件格式", str(caught.exception))

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config_file(self.dir / "nope.yml")


class TestHmr(unittest.TestCase):
    """真实热替换：改磁盘上的文件，观察插件被替换。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log: list[str] = []
        (self.dir / "shared.py").write_text('SHARED = "s1"\n', encoding="utf-8")
        (self.dir / "plug.py").write_text(
            "from shared import SHARED\n\n"
            "def apply(ctx, config):\n"
            '    ctx.on("probe", lambda: SHARED)\n',
            encoding="utf-8",
        )
        sys.path.insert(0, str(self.dir))

        self.ctx = Context()
        self.ctx.plugin(Loader, {"base_url": str(self.dir), "logs": True})
        self.ctx.loader.load(
            [{"id": "p", "name": str(self.dir / "plug.py")}]
        )
        self.ctx.plugin(
            Hmr,
            {
                "base": str(self.dir),
                "root": ["."],
                "debounce": 50,
                "poll_interval": 100,
            },
        )
        self._wait_baseline()
        self._reloads = self.ctx.hmr.reload_count

    def tearDown(self) -> None:
        self.ctx.hmr.stop()
        # 关键：把本用例导入的模块从 sys.modules 里清掉。
        # 否则下一个用例的 ``from shared import ...`` 会命中上一个临时目录的
        # 同名模块（模块名相同、文件不同），测试之间互相污染。
        for name in list(sys.modules):
            module = sys.modules.get(name)
            source = getattr(module, "__file__", None)
            if source and str(Path(source).resolve()).startswith(str(self.dir)):
                del sys.modules[name]
        sys.modules.pop("shared", None)
        sys.path.remove(str(self.dir))
        self.tmp.cleanup()

    @property
    def probe(self):
        return self.ctx.serial("probe")

    def _wait_baseline(self, timeout: float = 3.0) -> None:
        """等首轮扫描把 mtime 基线建好（Hmr.init 里已同步扫一次，这里只是保险）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ctx.hmr._mtimes:
                return
            time.sleep(0.02)
        self.fail("HMR 首轮扫描超时")

    def _await(self, predicate, message: str, timeout: float = 6.0) -> None:
        """事件驱动地等待，避免用固定 sleep 造成的时序抖动。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail(f"超时：{message}")

    def _write(self, name: str, text: str) -> None:
        # 留一点间隔，保证 mtime 严格变新（轮询靠 mtime 判断）
        time.sleep(0.1)
        (self.dir / name).write_text(textwrap.dedent(text), encoding="utf-8")

    def _await_reload(self) -> None:
        """等到热替换真正发生一次。"""
        target = self._reloads + 1
        self._await(
            lambda: self.ctx.hmr.reload_count >= target,
            f"热替换未触发（当前 reload_count={self.ctx.hmr.reload_count}）",
        )
        self._reloads = self.ctx.hmr.reload_count

    def _await_error(self) -> None:
        """等到热替换失败并被捕获。"""
        self._await(
            lambda: self.ctx.hmr.last_error is not None,
            "热替换失败但未被记录到 last_error",
        )

    def _await_recovery(self) -> None:
        """等到一次失败后的成功恢复。"""
        target = self._reloads + 1
        self._await(
            lambda: self.ctx.hmr.reload_count >= target
            and self.ctx.hmr.last_error is None,
            "语法错误修复后未恢复",
        )
        self._reloads = self.ctx.hmr.reload_count

    def test_initial_load(self):
        self.assertEqual(self.probe, "s1")

    def test_reload_on_entry_change(self):
        self._write(
            "plug.py",
            """
            from shared import SHARED

            def apply(ctx, config):
                ctx.on("probe", lambda: SHARED + "-v2")
            """,
        )
        self._await_reload()
        self.assertEqual(self.probe, "s1-v2")
        self.assertEqual(self.ctx.hmr.reload_count, 1)

    def test_dependency_propagation(self):
        """改被依赖的模块，依赖它的插件要一起重载。"""
        self._write("shared.py", 'SHARED = "s2"\n')
        self._await_reload()
        self.assertEqual(self.probe, "s2")

    def test_syntax_error_rolls_back(self):
        self._write(
            "plug.py",
            """
            from shared import SHARED

            def apply(ctx, config):
                ctx.on("probe", lambda: SHARED + "-v2")
            """,
        )
        self._await_reload()
        self.assertEqual(self.probe, "s1-v2")

        self._write("plug.py", "def apply(ctx, config:\n")
        self._await_error()
        self.assertIsInstance(self.ctx.hmr.last_error, SyntaxError)
        # 回滚后仍是上一个可用版本
        self.assertEqual(self.probe, "s1-v2")

    def test_recovers_after_fix(self):
        self._write("plug.py", "def apply(ctx, config:\n")
        self._await_error()
        self.assertIsInstance(self.ctx.hmr.last_error, SyntaxError)

        self._write(
            "plug.py",
            """
            from shared import SHARED

            def apply(ctx, config):
                ctx.on("probe", lambda: SHARED + "-fixed")
            """,
        )
        self._await_recovery()
        self.assertIsNone(self.ctx.hmr.last_error)
        self.assertEqual(self.probe, "s1-fixed")

    def test_no_listener_leak(self):
        before = self.ctx.events.hook_count()
        for index in range(3):
            self._write(
                "plug.py",
                f"""
                from shared import SHARED

                def apply(ctx, config):
                    ctx.on("probe", lambda: SHARED + "-r{index}")
                """,
            )
            self._await_reload()
        self.assertEqual(self.ctx.hmr.reload_count, 3)
        self.assertEqual(self.ctx.events.hook_count(), before)

    def test_loader_entry_stays_consistent(self):
        """热替换后 loader 的条目仍指向活着的 Fiber。"""
        self._write(
            "plug.py",
            """
            from shared import SHARED

            def apply(ctx, config):
                ctx.on("probe", lambda: SHARED + "-v2")
            """,
        )
        self._await_reload()
        entry = self.ctx.loader.resolve("p")
        self.assertEqual(entry.fiber.state.name, "ACTIVE")
        self.assertEqual(entry.fiber.uid is not None, True)

    def test_dependency_graph(self):
        import sys as _sys

        plug = _sys.modules[
            [n for n, m in _sys.modules.items() if getattr(m, "__file__", "") ==
             str((self.dir / "plug.py").resolve())][0]
        ]
        deps = self.ctx.hmr.module_dependencies(plug)
        self.assertEqual(deps, {str((self.dir / "shared.py").resolve())})


if __name__ == "__main__":
    unittest.main()

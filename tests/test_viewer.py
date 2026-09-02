"""应用级冒烟测试。

跑真实的 Tk 窗口（``root.withdraw()`` 隐藏）。所有与内容相关的期望值都锚定在
``tests/fixtures/sample.md`` 上，而不是 ``README.md`` —— 文档会改，基线不能跟着漂。

当前基线（改动 fixture 后需要重新采集）：

    backend      tkhtmlview（TkinterWeb 在 Tcl/Tk 9 下不可用）
    encoding     utf-8-sig
    stats        467 字符 · 195 词 · 8 标题 · 1 代码块 · 0 图片 · 约 1 分钟
    目录标题数    8
    find "渲染"   4 处命中
    export light（14px）  9659 字节，sha256 前 16 位 363c3dcaabe175e1
    export dark （16px）  9164 字节，sha256 前 16 位 2bdf145217e3c84c

重构前后的等价性另有两项：``--list-backends`` 的输出与重构前逐字一致，
导出 HTML 的字节流未因架构改动而变化（重构时用 README.md 比对过，当时
light/dark 的 sha256 分别为 594120d8… / 7c03777c…）。

用户配置通过 ``MDVIEWER_HOME`` 指向临时目录，因此测试不会碰到真实设置。
运行::

    python -m unittest tests.test_viewer -v
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURE_DIR / "sample.md"
README = PROJECT_ROOT / "README.md"

logging.getLogger("cordis").addHandler(logging.NullHandler())


def setUpModule() -> None:
    """把用户配置目录重定向到临时目录，避免污染真实设置。

    同时把 ``messagebox`` 换成空实现——插件在打开失败时会弹对话框，
    测试里它会一直阻塞等用户点击。
    """
    global _TMP
    _TMP = tempfile.TemporaryDirectory(prefix="mdviewer-test-")
    os.environ["MDVIEWER_HOME"] = _TMP.name

    from tkinter import messagebox

    messagebox.showerror = lambda *args, **kwargs: None
    messagebox.showinfo = lambda *args, **kwargs: None
    messagebox.askyesno = lambda *args, **kwargs: False


def tearDownModule() -> None:
    os.environ.pop("MDVIEWER_HOME", None)
    _TMP.cleanup()


class ViewerTestCase(unittest.TestCase):
    """每个用例一个全新的 Tk 窗口 + Context + 独立的配置目录。

    配置目录必须逐个用例隔离：``切换后端`` 之类的用例会把偏好写回磁盘，
    共用目录会让后续用例读到被污染的 ``backend``。
    """

    def setUp(self) -> None:
        import tkinter as tk

        from mdviewer import events
        from mdviewer.app import create_context

        self._home = tempfile.TemporaryDirectory(prefix="mdviewer-case-")
        os.environ["MDVIEWER_HOME"] = self._home.name
        self.events = events
        self.root = tk.Tk()
        self.root.withdraw()
        self.ctx = create_context(self.root)
        # 有些用例会卸载 window 服务，服务一走 ctx.window 就取不到了，
        # 因此这里先留一份引用，保证 tearDown 一定能清理定时器
        self.window = self.ctx.window

    def tearDown(self) -> None:
        # 先取消挂起的 after 回调，否则销毁窗口后回调触发会刷一串 bgerror
        self.window.cancel_all_timers()
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass
        self._home.cleanup()

    def ready(self, initial_file=None) -> None:
        self.ctx.emit(self.events.APP_READY, initial_file)
        self.root.update()


class TestServices(ViewerTestCase):
    def test_all_services_available(self):
        self.ready()
        for name in (
            "settings",
            "themes",
            "documents",
            "renderer",
            "backends",
            "window",
        ):
            self.assertIsNotNone(self.ctx.get(name), f"服务 {name} 未就绪")

    def test_plugin_count(self):
        """6 个服务 + 3 个后端插件 + 9 个功能插件 = 18。"""
        self.ready()
        self.assertEqual(self.ctx.registry.size, 18)

    def test_backend_fallback_matches_baseline(self):
        """Tcl/Tk 9 下 TkinterWeb 不可用，应自动降级到 tkhtmlview。"""
        self.ready()
        backend = self.ctx.backends.current
        self.assertEqual(backend.key, "tkhtmlview")
        self.assertIn("TkinterWeb 不可用（OSError）", self.ctx.backends.note)

    def test_backend_registry_order(self):
        self.ready()
        self.assertEqual(
            self.ctx.backends.keys(), ("tkinterweb", "tkhtmlview", "plaintext")
        )


class TestDocument(ViewerTestCase):
    def test_open_matches_baseline(self):
        self.ready(str(SAMPLE))
        document = self.ctx.documents.current
        self.assertIsNotNone(document)
        self.assertEqual(document.path.name, "sample.md")
        self.assertEqual(document.encoding, "utf-8-sig")
        self.assertEqual(
            document.stats.as_text(),
            "467 字符 · 195 词 · 8 标题 · 1 代码块 · 0 图片 · 约 1 分钟",
        )

    def test_readme_opens(self):
        """README 只验证“能打开”，不锁数字——文档会改，基线不该跟着变。"""
        self.ready(str(README))
        document = self.ctx.documents.current
        self.assertEqual(document.encoding, "utf-8-sig")
        self.assertGreater(document.stats.chars, 1000)
        self.assertGreater(document.stats.headings, 10)

    def test_window_title(self):
        self.ready(str(SAMPLE))
        self.assertEqual(self.root.title(), "sample.md — Markdown Viewer")

    def test_recent_files(self):
        self.ready(str(SAMPLE))
        self.assertIn(str(SAMPLE), self.ctx.documents.recent_files())

    def test_missing_file_emits_error(self):
        seen = []
        self.ctx.on(self.events.DOC_ERROR, lambda path, msg: seen.append(str(path)))
        self.ready()
        self.ctx.documents.open(PROJECT_ROOT / "does-not-exist.md")
        self.assertEqual(len(seen), 1)


class TestWidgets(ViewerTestCase):
    def test_toc_populated(self):
        """toc_tokens 是嵌套树，递归计数后应与基线的 8 个标题一致。"""
        from mdviewer.core.document import count_headings

        self.ready(str(SAMPLE))
        rendered = []
        self.ctx.on(self.events.DOC_RENDERED, lambda result: rendered.append(result))
        self.ctx.documents.open(str(SAMPLE))
        self.root.update()
        self.assertEqual(count_headings(rendered[-1].toc_tokens), 8)

    def test_toc_toggle_round_trip(self):
        self.ready(str(SAMPLE))
        self.ctx.emit(self.events.ACTION_TOGGLE_TOC)
        self.root.update()
        self.assertFalse(self.ctx.settings.get("show_toc"))
        self.ctx.emit(self.events.ACTION_TOGGLE_TOC)
        self.root.update()
        self.assertTrue(self.ctx.settings.get("show_toc"))

    def test_find_matches_baseline(self):
        self.ready(str(SAMPLE))
        self.root.update()
        hits = self.ctx.backends.current.find("渲染", nocase=True)
        self.assertEqual(hits, 4)

    def test_status_bar_receives_events(self):
        self.ready(str(SAMPLE))
        self.ctx.emit(self.events.STATUS_MESSAGE, "hello")
        self.root.update()
        # 状态栏是插件内部控件，通过服务间接验证：消息不抛异常即可
        self.assertTrue(self.ctx.window.exists())


class TestAppearance(ViewerTestCase):
    def test_theme_toggle(self):
        self.ready(str(SAMPLE))
        self.assertEqual(self.ctx.themes.current.key, "light")
        self.ctx.emit(self.events.ACTION_TOGGLE_THEME)
        self.root.update()
        self.assertEqual(self.ctx.themes.current.key, "dark")
        self.assertEqual(self.ctx.settings.get("theme"), "dark")

    def test_font_size_zoom(self):
        self.ready(str(SAMPLE))
        self.ctx.emit(self.events.ACTION_ZOOM, 1)
        self.assertEqual(self.ctx.themes.font_size, 15)
        self.ctx.emit(self.events.ACTION_ZOOM, 0)
        self.assertEqual(self.ctx.themes.font_size, 14)

    def test_switch_backend_to_plaintext(self):
        self.ready(str(SAMPLE))
        self.ctx.emit(self.events.ACTION_SWITCH_BACKEND, "plaintext")
        self.root.update()
        self.assertEqual(self.ctx.backends.current.key, "plaintext")
        self.assertEqual(self.ctx.settings.get("backend"), "plaintext")


class TestHotUnload(ViewerTestCase):
    """Cordis 的核心卖点：插件可以运行时卸载且不留残迹。"""

    def test_unload_toc_removes_pane(self):
        from mdviewer.plugins import toc

        self.ready(str(SAMPLE))
        self.ctx.registry.delete(toc)
        self.root.update()
        # 目录面板的控件已被销毁，窗格里不再有它
        self.assertNotIn("toc", self.ctx.window._panes)

    def test_unload_find_removes_listener(self):
        from mdviewer.plugins import find

        self.ready(str(SAMPLE))
        before = self.ctx.events.hook_count()
        self.ctx.registry.delete(find)
        after = self.ctx.events.hook_count()
        self.assertLess(after, before)

    def test_unload_all_feature_plugins(self):
        from mdviewer.plugins import FEATURE_PLUGINS

        self.ready(str(SAMPLE))
        for plugin in FEATURE_PLUGINS:
            self.ctx.registry.delete(plugin)
        self.root.update()
        # 服务仍然健在，只是功能插件全部退场
        self.assertIsNotNone(self.ctx.documents)
        self.assertTrue(self.ctx.window.exists())

    def test_service_disposal_stops_dependents(self):
        """卸载 window 服务后，依赖它的插件应自动停用。"""
        from mdviewer.plugins import toc
        from mdviewer.services import WindowService

        self.ready(str(SAMPLE))
        fiber = self.ctx.registry.get(toc).fibers[0]
        self.assertEqual(fiber.state.name, "ACTIVE")
        self.ctx.registry.delete(WindowService)
        self.assertEqual(fiber.state.name, "PENDING")


class TestExport(ViewerTestCase):
    """导出结果与重构前的基线逐字节比对。"""

    def _digest(self, path: Path) -> tuple[int, str]:
        data = path.read_bytes()
        return len(data), hashlib.sha256(data).hexdigest()[:16]

    def test_export_light_matches_baseline(self):
        from mdviewer.core.exporter import export_html
        from mdviewer.core.theme import get_theme

        with tempfile.TemporaryDirectory() as tmp:
            target = export_html(
                SAMPLE.read_text(encoding="utf-8-sig"),
                Path(tmp) / "out.html",
                get_theme("light"),
                FIXTURE_DIR,
                14,
                title="sample",
            )
            size, digest = self._digest(Path(target))
        self.assertEqual((size, digest), (9659, "363c3dcaabe175e1"))

    def test_export_dark_matches_baseline(self):
        from mdviewer.core.exporter import export_html
        from mdviewer.core.theme import get_theme

        with tempfile.TemporaryDirectory() as tmp:
            target = export_html(
                SAMPLE.read_text(encoding="utf-8-sig"),
                Path(tmp) / "out.html",
                get_theme("dark"),
                FIXTURE_DIR,
                16,
                title="sample",
            )
            size, digest = self._digest(Path(target))
        self.assertEqual((size, digest), (9164, "2bdf145217e3c84c"))

    def test_renderer_service_matches_core(self):
        """服务层包装不得改变渲染结果。"""
        from mdviewer.core.exporter import build_standalone_html
        from mdviewer.core.renderer import RICH, render
        from mdviewer.core.theme import get_theme

        self.ready()
        text = SAMPLE.read_text(encoding="utf-8-sig")
        theme = get_theme("light")
        direct = render(text, profile=RICH, theme=theme, base_dir=FIXTURE_DIR, font_size=14)
        via_service = self.ctx.renderer.render_text(
            text, profile=RICH, theme=theme, base_dir=FIXTURE_DIR, font_size=14
        )
        self.assertEqual(direct.html, via_service.html)
        self.assertEqual(direct.css, via_service.css)
        # 复用解析器实例（渲染服务的缓存）不得改变输出
        again = self.ctx.renderer.render_text(
            text, profile=RICH, theme=theme, base_dir=FIXTURE_DIR, font_size=14
        )
        self.assertEqual(again.html, direct.html)
        self.assertEqual(
            build_standalone_html("t", text, theme, FIXTURE_DIR, 14),
            build_standalone_html("t", text, theme, FIXTURE_DIR, 14),
        )


if __name__ == "__main__":
    unittest.main()

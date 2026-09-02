"""命令行入口。

除了启动 GUI，也提供不依赖图形界面的批量转换能力：``--to-html`` 只加载
:mod:`mdviewer.core`，不会 import ``tkinter``。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core.config import APP_NAME
from .core.theme import THEMES, get_theme


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdviewer",
        description=f"{APP_NAME} —— 本地 Markdown 查看器",
    )
    parser.add_argument("file", nargs="?", help="要打开的 Markdown 文件")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")

    convert = parser.add_argument_group("无界面转换")
    convert.add_argument("--to-html", metavar="OUTPUT", help="把 Markdown 转换为独立 HTML")
    convert.add_argument(
        "--theme",
        choices=sorted(THEMES),
        default="light",
        help="转换时使用的主题（默认: light）",
    )
    convert.add_argument("--font-size", type=int, default=14, help="正文字号（默认: 14）")

    info = parser.add_argument_group("环境信息")
    info.add_argument(
        "--list-backends", action="store_true", help="列出渲染后端并检测可用性"
    )
    info.add_argument(
        "--list-plugins", action="store_true", help="列出已注册的插件与依赖"
    )
    return parser


def _convert(args: argparse.Namespace) -> int:
    from .core.document import read_text
    from .core.exporter import export_html

    source = Path(args.file)
    if not source.is_file():
        print(f"错误：文件不存在 {source}", file=sys.stderr)
        return 2
    text, _encoding = read_text(source)
    target = export_html(
        text,
        Path(args.to_html),
        get_theme(args.theme),
        source.parent,
        args.font_size,
        title=source.stem,
    )
    print(f"已导出：{target}")
    return 0


def _list_backends() -> int:
    """逐个探测已注册的渲染后端，输出当前环境会选中哪一个。"""
    import tkinter as tk

    from .app import create_context
    from .plugins import BACKEND_PLUGINS

    root = tk.Tk()
    root.withdraw()
    try:
        ctx = create_context(root, plugins=BACKEND_PLUGINS)
        results = ctx.backends.probe_all()
    finally:
        root.destroy()

    winner: str | None = None
    notes: list[str] = []
    for spec, ok, error in results:
        if ok and winner is None:
            winner = spec.key
        elif not ok and winner is None:
            notes.append(f"{spec.short} 不可用（{type(error).__name__}）")
    for spec, ok, _error in results:
        mark = "*" if spec.key == winner else " "
        print(f"{mark} {spec.short}")

    if winner is None:
        print("\n当前环境没有任何可用的渲染后端。")
        return 1
    winner_spec = ctx.backends.spec(winner)
    print(f"\n当前环境将使用：{winner_spec.label}")
    if notes:
        print(f"降级说明：{'；'.join(notes)}")
    return 0


def _list_plugins() -> int:
    """列出插件清单（不需要 Tk 窗口，只做静态信息输出）。"""
    from .plugins import PLUGIN_ORDER

    print(f"{'插件':<22}{'依赖'}")
    print("-" * 60)
    for plugin in PLUGIN_ORDER:
        inject = getattr(plugin, "inject", None) or []
        print(f"{getattr(plugin, 'name', plugin.__name__):<22}{', '.join(inject) or '—'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_backends:
        return _list_backends()
    if args.list_plugins:
        return _list_plugins()

    if args.to_html:
        if not args.file:
            print("错误：--to-html 需要同时指定输入文件", file=sys.stderr)
            return 2
        return _convert(args)

    from .app import main as gui_main

    return gui_main(args.file)


if __name__ == "__main__":
    raise SystemExit(main())

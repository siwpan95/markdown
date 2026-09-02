"""自动重载插件。

每秒轮询一次当前文件的 mtime，发现变新就重新读取。用轮询而不是
``watchdog`` 之类的文件系统监听，是为了保持零额外依赖——代价是最长 1 秒延迟。

轮询定时器通过 ``window.after`` 申请，窗口关闭时会被统一取消，不会在 Tk
主循环里留下指向已销毁控件的回调。
"""

from __future__ import annotations

from typing import Any

from .. import events

#: 轮询间隔（毫秒）
RELOAD_INTERVAL_MS = 1000


def apply(ctx: Any, config: Any = None) -> None:
    interval = RELOAD_INTERVAL_MS
    if isinstance(config, dict):
        interval = int(config.get("interval", interval))

    def poll() -> None:
        if ctx.settings.get("auto_reload", True) and ctx.documents.has_external_change():
            # open() 会刷新 mtime，因此这里不需要手动同步
            ctx.documents.reload()
        if ctx.window.exists():
            ctx.window.after(interval, poll)

    def start(_initial_file: Any = None) -> None:
        ctx.window.after(interval, poll)

    ctx.on(events.APP_READY, start)


apply.name = "auto-reload"
apply.inject = ["settings", "documents", "window"]

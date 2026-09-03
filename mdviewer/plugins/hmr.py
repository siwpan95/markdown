"""开发期热替换插件。

默认**不启用**——只有显式传 ``watch=True``（或命令行 ``--watch``）时才会注册
:class:`~cordis.hmr.Hmr`。

启用后改 ``mdviewer/plugins/*.py`` 或 ``mdviewer/services/*.py`` 里的代码，
对应的插件会在不重启窗口的前提下被替换：旧 Fiber 的监听器、控件、定时器按
Cordis 的规矩逆序清理，新代码以同样的配置重新加载，其余插件状态保留。

线程模型（Tkinter 的唯一硬性约束）：

    监听线程 ──发现变化──> 攒够防抖窗口 ──> window.after(...) ──> 主线程执行重载

``window.after`` 是 Tk 的定时器，回调跑在主线程，因此可以安全地销毁 / 创建控件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: 项目根目录（hmr.py → plugins → mdviewer → 根），作为监听基准
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: 监听配置
DEFAULT_ROOTS = ["mdviewer"]
DEFAULT_IGNORED = ["**/.*", "**/__pycache__", "**/tests"]


def apply(ctx: Any, config: Any = None) -> None:
    from cordis.hmr import Hmr

    options = dict(config or {})
    options.setdefault("base", str(PROJECT_ROOT))
    options.setdefault("root", DEFAULT_ROOTS)
    options.setdefault("ignored", DEFAULT_IGNORED)
    options.setdefault("debounce", 200)
    options.setdefault("poll_interval", 300)
    # 关键：让重载跑在 Tk 主线程上
    options.setdefault("schedule", ctx.window.after)

    ctx.plugin(Hmr, options)


apply.name = "hmr"
apply.inject = ["window"]

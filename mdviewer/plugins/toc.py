"""目录侧栏插件。

把自己注册成 :class:`WindowService` 的一个可显隐侧栏，其余全部由事件驱动：

* ``document/rendered`` → 重建目录树；
* ``action/toggle-toc`` → 切换显隐并写回设置；
* ``settings/change(show_toc)`` → 同步显隐（这样菜单里的勾选框和快捷键
  无论谁改了设置，面板状态都会跟上）。
"""

from __future__ import annotations

from typing import Any

from .. import events

PANE_NAME = "toc"


def apply(ctx: Any, config: Any = None) -> None:
    from ..widgets.toc_panel import TocPanel

    panel = TocPanel(
        ctx.window.body,
        on_select=lambda heading: ctx.emit(events.ACTION_JUMP, heading),
    )
    # add_pane 返回撤销函数，交给 Fiber 托管：插件卸载时面板与注册项一起消失
    ctx.effect(lambda: ctx.window.add_pane(PANE_NAME, panel, width=240))
    if ctx.settings.get("show_toc", True):
        ctx.window.show_pane(PANE_NAME)

    def on_rendered(result: Any) -> None:
        panel.populate(result.toc_tokens)

    def on_toggle() -> None:
        visible = ctx.window.toggle_pane(PANE_NAME)
        ctx.settings.update(show_toc=visible)

    def on_settings_change(key: str, value: Any) -> None:
        if key != "show_toc":
            return
        if value:
            ctx.window.show_pane(PANE_NAME)
        else:
            ctx.window.hide_pane(PANE_NAME)

    ctx.on(events.DOC_RENDERED, on_rendered)
    ctx.on(events.ACTION_TOGGLE_TOC, on_toggle)
    ctx.on(events.SETTINGS_CHANGE, on_settings_change)


apply.name = "toc"
apply.inject = ["settings", "window"]

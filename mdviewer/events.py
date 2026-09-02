"""事件契约。

Cordis 要求组件之间的依赖**显式声明**，而事件名就是最容易漂移的一处隐式依赖。
这里把全部事件名集中成常量，插件按名字订阅，避免散落的字符串字面量。

事件分三类：

``app/*``
    应用生命周期。
``document/*``、``theme/*``、``backend/*``、``settings/*``
    状态广播——谁都可以监听，用来做响应式联动。
``action/*``
    用户动作。由 ``shell`` 插件（菜单/工具栏/快捷键）发出，具体行为由
    功能插件实现。这样 shell 不需要知道“导出”是怎么实现的。
``menu/*``
    菜单构建钩子。shell 建好菜单后广播一次，其他插件往里加条目。
"""

from __future__ import annotations

# --------------------------------------------------------------------- 生命周期
#: ``(initial_file: str | None)`` —— 所有插件加载完毕后发出
APP_READY = "app/ready"
#: 窗口关闭前发出，用于保存几何信息等收尾
APP_CLOSE = "app/close"

# --------------------------------------------------------------------- 文档
#: ``(doc: Document)`` 打开成功
DOC_OPEN = "document/open"
#: ``(path: Path, message: str)`` 打开失败（不存在 / 二进制 / 读取错误）
DOC_ERROR = "document/error"
#: ``(result: RenderResult)`` 渲染完成，目录与状态栏据此刷新
DOC_RENDERED = "document/rendered"
#: ``(doc: Document)`` 自动重载触发的重新读取
DOC_RELOADED = "document/reloaded"

# --------------------------------------------------------------------- 外观
#: ``(theme: Theme)``
THEME_CHANGE = "theme/change"
#: ``(size: int)``
FONT_SIZE_CHANGE = "view/font-size"
#: ``(backend: Backend)``
BACKEND_CHANGE = "backend/change"
#: ``(key: str, value: Any)`` 任一设置项变化
SETTINGS_CHANGE = "settings/change"

# --------------------------------------------------------------------- 杂项
#: ``(text: str)`` 往状态栏左侧写一条消息
STATUS_MESSAGE = "status/message"
#: ``(target: LinkTarget)`` 正文里的链接被点击
LINK_OPEN = "link/open"
#: ``(heading: str)`` 请求正文滚动到某个标题
ACTION_JUMP = "action/jump"

# --------------------------------------------------------------------- 用户动作
ACTION_OPEN_FILE = "action/open-file"
ACTION_RELOAD = "action/reload"
ACTION_EXPORT_HTML = "action/export-html"
ACTION_OPEN_BROWSER = "action/open-browser"
ACTION_QUIT = "action/quit"
ACTION_TOGGLE_THEME = "action/toggle-theme"
ACTION_TOGGLE_TOC = "action/toggle-toc"
ACTION_SHOW_FIND = "action/show-find"
ACTION_HIDE_FIND = "action/hide-find"
#: ``(delta: int)`` 正数放大、负数缩小、0 重置
ACTION_ZOOM = "action/zoom"
#: ``(key: str)`` 切换渲染后端
ACTION_SWITCH_BACKEND = "action/switch-backend"
ACTION_ABOUT = "action/about"

# --------------------------------------------------------------------- 菜单
MENU_FILE = "menu/file"
MENU_VIEW = "menu/view"
MENU_HELP = "menu/help"


__all__ = [
    "ACTION_ABOUT",
    "ACTION_EXPORT_HTML",
    "ACTION_HIDE_FIND",
    "ACTION_JUMP",
    "ACTION_OPEN_BROWSER",
    "ACTION_OPEN_FILE",
    "ACTION_QUIT",
    "ACTION_RELOAD",
    "ACTION_SHOW_FIND",
    "ACTION_SWITCH_BACKEND",
    "ACTION_TOGGLE_THEME",
    "ACTION_TOGGLE_TOC",
    "ACTION_ZOOM",
    "APP_CLOSE",
    "APP_READY",
    "BACKEND_CHANGE",
    "DOC_ERROR",
    "DOC_OPEN",
    "DOC_RELOADED",
    "DOC_RENDERED",
    "FONT_SIZE_CHANGE",
    "LINK_OPEN",
    "MENU_FILE",
    "MENU_HELP",
    "MENU_VIEW",
    "SETTINGS_CHANGE",
    "STATUS_MESSAGE",
    "THEME_CHANGE",
]

"""纯逻辑层：不依赖 Tkinter，可在无图形环境下单独使用。

这一层是重构前的 ``mdviewer`` 主体，职责保持不变，只是从包根挪进 ``core``，
好让上层的 ``services`` / ``plugins`` 与它们区分开：

    config      常量与用户设置持久化
    theme       主题配色（同时产出 CSS 与受限内联样式）
    document    文件读取（编码探测）与统计
    highlight   自研的 Pygments 代码块高亮扩展
    renderer    Markdown → HTML，按后端能力输出 rich / simple 两种档位
    exporter    导出独立 HTML

无界面的批量转换（``python main.py README.md --to-html out.html``）只会加载
这一层，不会触碰 ``tkinter``。
"""

from .config import (
    APP_ID,
    APP_NAME,
    FILE_TYPES,
    MAX_RECENT_FILES,
    SUPPORTED_SUFFIXES,
    VERSION,
    Settings,
    config_dir,
    settings_path,
)
from .document import DocStats, Document, compute_stats, read_text
from .exporter import build_standalone_html, export_html
from .theme import DARK, LIGHT, THEMES, Theme, build_css, get_theme

__all__ = [
    "APP_ID",
    "APP_NAME",
    "DARK",
    "FILE_TYPES",
    "LIGHT",
    "MAX_RECENT_FILES",
    "SUPPORTED_SUFFIXES",
    "THEMES",
    "VERSION",
    "DocStats",
    "Document",
    "Settings",
    "Theme",
    "build_css",
    "build_standalone_html",
    "compute_stats",
    "config_dir",
    "export_html",
    "get_theme",
    "read_text",
    "settings_path",
]

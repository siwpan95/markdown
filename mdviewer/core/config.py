"""全局常量与用户设置的持久化。

设置以 JSON 形式存放在用户目录下：
    Windows: %USERPROFILE%\\.mdviewer\\settings.json
    其他:    ~/.mdviewer/settings.json

可通过环境变量 ``MDVIEWER_HOME`` 覆盖该目录，便于便携化部署或测试。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

APP_ID = "mdviewer"
APP_NAME = "Markdown Viewer"
VERSION = "2.0.0"

#: 打开对话框中展示、以及目录扫描时识别的扩展名
SUPPORTED_SUFFIXES = (
    ".md",
    ".markdown",
    ".mdown",
    ".mkd",
    ".mkdn",
    ".mdtext",
    ".mdtxt",
    ".txt",
)

#: 最近打开文件列表的最大长度
MAX_RECENT_FILES = 15

#: 支持的界面语言无关，仅用于文件对话框
FILE_TYPES = (
    ("Markdown 文件", "*.md *.markdown *.mdown *.mkd *.mkdn *.mdtext *.mdtxt"),
    ("文本文件", "*.txt"),
    ("所有文件", "*.*"),
)


def config_dir() -> Path:
    """返回（并在必要时创建）存放配置与缓存的目录。"""
    base = Path(os.environ.get("MDVIEWER_HOME") or (Path.home() / f".{APP_ID}"))
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 用户目录不可写时退回到临时目录，保证程序仍然可用
        import tempfile

        base = Path(tempfile.gettempdir()) / f".{APP_ID}"
        base.mkdir(parents=True, exist_ok=True)
    return base


def settings_path() -> Path:
    """返回设置文件的路径。"""
    return config_dir() / "settings.json"


@dataclass
class Settings:
    """可持久化的用户偏好。"""

    theme: str = "light"
    backend: str = "auto"
    base_font_size: int = 14
    show_toc: bool = True
    auto_reload: bool = True
    word_wrap: bool = True
    window_geometry: str = "1100x720"
    recent_files: list[str] = field(default_factory=list)

    _MIN_FONT_SIZE = 8
    _MAX_FONT_SIZE = 36

    # ------------------------------------------------------------------ 读写
    @classmethod
    def load(cls) -> "Settings":
        """从磁盘加载设置；文件缺失或损坏时回退为默认值。"""
        path = settings_path()
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()

        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}
        clean = {k: v for k, v in data.items() if k in known}
        settings = cls(**clean)
        settings.recent_files = [
            p for p in settings.recent_files if isinstance(p, str) and p
        ][:MAX_RECENT_FILES]
        settings.base_font_size = max(
            cls._MIN_FONT_SIZE,
            min(cls._MAX_FONT_SIZE, int(settings.base_font_size)),
        )
        return settings

    def save(self) -> None:
        """写回磁盘，失败时静默忽略（设置丢失不应影响主功能）。"""
        data = {
            "theme": self.theme,
            "backend": self.backend,
            "base_font_size": self.base_font_size,
            "show_toc": self.show_toc,
            "auto_reload": self.auto_reload,
            "word_wrap": self.word_wrap,
            "window_geometry": self.window_geometry,
            "recent_files": self.recent_files[:MAX_RECENT_FILES],
        }
        try:
            settings_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ 最近文件
    def add_recent(self, path: str | Path) -> None:
        """把一个文件路径提到最近列表最前面。"""
        text = str(Path(path))
        self.recent_files = [text] + [p for p in self.recent_files if p != text]
        self.recent_files = self.recent_files[:MAX_RECENT_FILES]

    def remove_recent(self, path: str | Path) -> None:
        """从最近列表中移除某个路径（例如文件已被删除）。"""
        text = str(Path(path))
        self.recent_files = [p for p in self.recent_files if p != text]

    def valid_recent_files(self) -> list[str]:
        """返回仍然存在的最近文件路径。"""
        return [p for p in self.recent_files if Path(p).is_file()]

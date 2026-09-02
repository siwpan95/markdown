"""基于 TkinterWeb 的渲染后端（能力最强，但依赖环境）。

TkinterWeb 使用 Tkhtml 内核，支持 HTML 4.01 + CSS 2.1，样式表现远好于 tkhtmlview。
但它有两个现实约束：

1. 预编译的 Tkhtml 二进制只覆盖常见平台，且**不支持 Tcl/Tk 9**。Python 3.14 自带
   Tcl/Tk 9.0，此时创建 ``HtmlFrame`` 会抛出 ``OSError: No Tkhtml versions could be
   found for Tcl/Tk 9``；
2. 与 ``ttk.Notebook`` 在 64 位 Windows 上不兼容。

因此本后端只在“确实能用”的时候才被工厂选中，创建失败会自动降级。
"""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Callable

from ..core.renderer import RICH, RenderResult
from ..core.theme import Theme, build_css
from .base import Backend, LinkTarget


class TkinterWebBackend(Backend):
    """使用 TkinterWeb ``HtmlFrame`` 渲染完整 HTML。"""

    key = "tkinterweb"
    label = "TkinterWeb（增强模式）"
    supports_css = True
    supports_find = True
    supports_jump = True

    def __init__(
        self,
        master,
        theme: Theme,
        font_size: int = 14,
        on_link: Callable[[LinkTarget], None] | None = None,
    ) -> None:
        from tkinterweb import HtmlFrame

        self.theme = theme
        self.font_size = font_size
        self.on_link = on_link
        self._frame = HtmlFrame(master, messages_enabled=False)
        self._frame.on_link_click(self._handle_link)
        self._last_css = build_css(theme, font_size)

    # ------------------------------------------------------------------ 基础
    @property
    def widget(self):
        return self._frame

    def destroy(self) -> None:
        try:
            self._frame.destroy()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 渲染
    def set_content(self, result: RenderResult, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir
        css = result.css or self._last_css
        self._last_css = css
        body = result.html
        base_url = base_dir.as_uri() if base_dir is not None else None
        html = f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"
        try:
            self._frame.load_html(html, base_url)
        except TypeError:  # 旧版本不接受 base_url 参数
            self._frame.load_html(html)

    def show_message(self, title: str, message: str) -> None:
        self.set_content(
            RenderResult(
                html=f"<h2>{title}</h2><p>{message}</p>", css=self._last_css
            )
        )

    # ------------------------------------------------------------------ 外观
    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self._last_css = build_css(theme, self.font_size)

    def set_font_size(self, size: int) -> None:
        self.font_size = size
        self._last_css = build_css(self.theme, size)

    # ------------------------------------------------------------------ 链接
    def _handle_link(self, url: str) -> None:
        if not url:
            return
        path = self._resolve_path(url)
        target = LinkTarget(url=url, path=path)
        if self.on_link is not None:
            self.on_link(target)
        else:
            webbrowser.open(url)

    def _resolve_path(self, url: str) -> Path | None:
        lowered = url.lower()
        if lowered.startswith(("http://", "https://", "ftp://", "mailto:")):
            return None
        if lowered.startswith("file://"):
            try:
                candidate = Path(url[7:].lstrip("/"))
            except ValueError:
                return None
        else:
            candidate = Path(url)
            if not candidate.is_absolute() and self.base_dir is not None:
                candidate = self.base_dir / url
        try:
            resolved = candidate.resolve()
        except (OSError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    # ------------------------------------------------------------------ 查找
    def find(self, query: str, *, nocase: bool = True) -> int:
        self.clear_find()
        if not query:
            return 0
        try:
            self._frame.find_text(query, True, nocase, True)
        except TypeError:
            try:
                self._frame.find_text(query)
            except Exception:  # noqa: BLE001
                return 0
        except Exception:  # noqa: BLE001
            return 0
        return 1

    def find_next(self) -> int:
        try:
            self._frame.find_text_next()
        except Exception:  # noqa: BLE001
            pass
        return 1

    def find_prev(self) -> int:
        try:
            self._frame.find_text_previous()
        except Exception:  # noqa: BLE001
            pass
        return 1

    def clear_find(self) -> None:
        try:
            self._frame.clear_selection()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 导航
    def scroll_to_text(self, text: str) -> bool:
        if not text:
            return False
        try:
            self._frame.find_text(text, True, True, True)
            return True
        except Exception:  # noqa: BLE001
            return False

    def scroll_to_top(self) -> None:
        try:
            self._frame.yview_moveto(0.0)
        except Exception:  # noqa: BLE001
            pass


def is_available(master) -> bool:
    """探测当前环境能否真正创建 TkinterWeb 控件。"""
    try:
        from tkinterweb import HtmlFrame

        probe = HtmlFrame(master, messages_enabled=False)
        probe.destroy()
        return True
    except Exception:  # noqa: BLE001 - OSError / TclError / ImportError 都算不可用
        return False


#: 该后端偏好完整 HTML 档位
PREFERRED_PROFILE = RICH

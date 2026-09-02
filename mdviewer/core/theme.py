"""主题定义。

渲染后端能力差异很大，因此主题需要同时提供两种产物：

* :func:`build_css` —— 完整 CSS 2.1 样式表，供 tkinterweb 后端与导出的 HTML 使用；
* :attr:`Theme.inline` —— 内联样式片段，供只识别 ``style=""`` 属性的 tkhtmlview 后端使用。

tkhtmlview 只支持 ``color`` / ``background-color`` / ``font-family`` / ``font-size``
/ ``text-align`` / ``text-decoration`` 六个属性，因此内联样式只能使用这些键。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    """一套配色方案。"""

    key: str
    label: str
    pygments_style: str

    #: 正文与页面
    body_bg: str
    body_fg: str
    muted_fg: str

    #: 各级标题
    heading_fg: str
    heading_border: str

    #: 链接、引用、分隔线
    link_fg: str
    quote_fg: str
    quote_bg: str
    hr_fg: str

    #: 代码
    code_bg: str
    code_fg: str
    code_inline_fg: str

    #: 表格与提示块
    table_border: str
    table_header_bg: str
    admonition_fg: str

    #: 查找高亮
    find_bg: str
    find_fg: str

    #: 只被受限后端（tkhtmlview）识别的内联样式片段
    inline: "dict[str, dict[str, str]]" = field(default_factory=dict)


def _inline(
    body_fg: str,
    heading_fg: str,
    link_fg: str,
    muted_fg: str,
    code_bg: str,
    code_inline_fg: str,
    quote_bg: str,
) -> dict[str, dict[str, str]]:
    """构造受限后端可用的内联样式表。

    只包含 tkhtmlview 能解析的六个属性，其余属性写了也会被忽略。
    这里必须显式给出正文与标题颜色：tkhtmlview 会把默认前景色硬编码为黑色，
    否则深色主题下会出现“黑底黑字”。
    """
    return {
        "heading": {"color": heading_fg},
        "link": {"color": link_fg},
        "blockquote": {"color": muted_fg, "background-color": quote_bg},
        "hr": {"color": muted_fg, "text-align": "center"},
        "code": {"color": code_inline_fg, "background-color": code_bg},
        "admonition": {"color": muted_fg},
        "caption": {"color": muted_fg, "text-align": "center"},
        "del": {"text-decoration": "line-through", "color": muted_fg},
        "body": {"color": body_fg},
    }


LIGHT = Theme(
    key="light",
    label="浅色",
    pygments_style="tango",
    body_bg="#ffffff",
    body_fg="#24292f",
    muted_fg="#6a737d",
    heading_fg="#1f2328",
    heading_border="#d8dee4",
    link_fg="#0969da",
    quote_fg="#57606a",
    quote_bg="#f6f8fa",
    hr_fg="#d0d7de",
    code_bg="#f6f8fa",
    code_fg="#1f2328",
    code_inline_fg="#b3284e",
    table_border="#d0d7de",
    table_header_bg="#f6f8fa",
    admonition_fg="#57606a",
    find_bg="#fff3a3",
    find_fg="#1f2328",
    inline=_inline(
        "#24292f", "#1f2328", "#0969da", "#6a737d", "#f6f8fa", "#b3284e", "#f6f8fa"
    ),
)

DARK = Theme(
    key="dark",
    label="深色",
    pygments_style="monokai",
    body_bg="#1e2127",
    body_fg="#d7dae0",
    muted_fg="#9aa0a6",
    heading_fg="#e6e9ef",
    heading_border="#3b4048",
    link_fg="#6cb6ff",
    quote_fg="#a8b0b8",
    quote_bg="#252932",
    hr_fg="#3b4048",
    code_bg="#282c34",
    code_fg="#d7dae0",
    code_inline_fg="#e5c07b",
    table_border="#3b4048",
    table_header_bg="#252932",
    admonition_fg="#a8b0b8",
    find_bg="#5a5f2c",
    find_fg="#ffffff",
    inline=_inline(
        "#d7dae0", "#e6e9ef", "#6cb6ff", "#9aa0a6", "#282c34", "#e5c07b", "#252932"
    ),
)

THEMES: dict[str, Theme] = {t.key: t for t in (LIGHT, DARK)}
DEFAULT_THEME = "light"


def get_theme(key: str) -> Theme:
    """按名称获取主题，未知名称回退到浅色主题。"""
    return THEMES.get(key, LIGHT)


def build_css(theme: Theme, base_font_size: int = 14, code_css: str = "") -> str:
    """生成一份 CSS 2.1 兼容的样式表。

    刻意不使用 flex / grid / 自定义属性等 Tkhtml 不支持的特性。
    """
    fs = base_font_size
    return f"""/* {theme.label}主题 — 由 mdviewer.theme 自动生成 */
body {{
    background-color: {theme.body_bg};
    color: {theme.body_fg};
    font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
    font-size: {fs}px;
    line-height: 1.7;
    margin: 0;
    padding: 16px 24px 64px 24px;
}}
h1, h2, h3, h4, h5, h6 {{
    color: {theme.heading_fg};
    font-weight: bold;
    margin: 1.4em 0 0.6em 0;
    line-height: 1.35;
}}
h1 {{ font-size: {int(fs * 1.9)}px; border-bottom: 2px solid {theme.heading_border}; padding-bottom: 6px; }}
h2 {{ font-size: {int(fs * 1.5)}px; border-bottom: 1px solid {theme.heading_border}; padding-bottom: 4px; }}
h3 {{ font-size: {int(fs * 1.25)}px; }}
h4 {{ font-size: {int(fs * 1.1)}px; }}
h5 {{ font-size: {int(fs * 1.0)}px; }}
h6 {{ font-size: {int(fs * 0.95)}px; color: {theme.muted_fg}; }}
p {{ margin: 0.7em 0; }}
a {{ color: {theme.link_fg}; text-decoration: underline; }}
ul, ol {{ margin: 0.6em 0 0.6em 1.6em; padding: 0; }}
li {{ margin: 0.25em 0; }}
blockquote {{
    color: {theme.quote_fg};
    background-color: {theme.quote_bg};
    border-left: 4px solid {theme.heading_border};
    margin: 1em 0;
    padding: 4px 14px;
}}
blockquote p {{ margin: 0.4em 0; }}
hr {{ border: 0; border-top: 1px solid {theme.hr_fg}; margin: 1.6em 0; }}
code {{
    font-family: Consolas, "Courier New", monospace;
    font-size: {max(int(fs * 0.92), 9)}px;
    background-color: {theme.code_bg};
    color: {theme.code_fg};
    padding: 1px 4px;
}}
pre {{
    background-color: {theme.code_bg};
    color: {theme.code_fg};
    border: 1px solid {theme.heading_border};
    padding: 10px 12px;
    margin: 1em 0;
    overflow: auto;
    white-space: pre;
}}
pre code {{
    background-color: transparent;
    padding: 0;
    font-size: {max(int(fs * 0.9), 9)}px;
}}
table {{
    border-collapse: collapse;
    margin: 1em 0;
    font-size: {max(int(fs * 0.95), 9)}px;
}}
th, td {{ border: 1px solid {theme.table_border}; padding: 6px 10px; }}
th {{ background-color: {theme.table_header_bg}; font-weight: bold; }}
tr:nth-child(even) td {{ background-color: {theme.quote_bg}; }}
img {{ max-width: 100%; }}
.admonition {{
    border-left: 4px solid {theme.heading_border};
    background-color: {theme.quote_bg};
    color: {theme.admonition_fg};
    margin: 1em 0;
    padding: 8px 14px;
}}
.admonition-title {{ font-weight: bold; color: {theme.heading_fg}; }}
.task-list-item {{ list-style-type: none; }}
{code_css}
"""

"""Markdown 文档的读取与统计。

读取部分解决一个常见问题：Markdown 文件可能是 UTF-8、带 BOM 的 UTF-8，
也可能是 GBK/GB18030 等本地编码。这里按可信度依次尝试，避免直接抛异常。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: 依次尝试的编码，覆盖国内最常见的几种情况
ENCODINGS: tuple[str, ...] = (
    "utf-8-sig",
    "utf-8",
    "gb18030",
    "big5",
    "utf-16",
    "latin-1",
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff]")
_WORD_RE = re.compile(r"[A-Za-z0-9_'\-]+")

#: 中文按字计、英文按词计，取 300 字/分钟的经验值
_WORDS_PER_MINUTE = 300


@dataclass
class DocStats:
    """文档的基本统计信息。"""

    chars: int = 0
    lines: int = 0
    cjk_chars: int = 0
    words: int = 0
    headings: int = 0
    code_blocks: int = 0
    images: int = 0
    links: int = 0
    tables: int = 0
    reading_minutes: int = 0

    def as_text(self) -> str:
        """格式化为状态栏展示的一行文本。"""
        return (
            f"{self.chars} 字符 · {self.cjk_chars + self.words} 词 · "
            f"{self.headings} 标题 · {self.code_blocks} 代码块 · "
            f"{self.images} 图片 · 约 {self.reading_minutes} 分钟"
        )


def read_text(path: str | Path) -> tuple[str, str]:
    """读取文本文件，返回 ``(内容, 实际使用的编码)``。

    所有编码都失败时，使用 ``utf-8`` 并替换非法字节，保证界面不会因此崩溃。
    """
    raw = Path(path).read_bytes()
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def looks_binary(path: str | Path) -> bool:
    """粗略判断文件是否为二进制（用于给出更友好的错误提示）。"""
    try:
        with open(path, "rb") as fp:
            return b"\x00" in fp.read(4096)
    except OSError:
        return False


def count_headings(toc_tokens: list[dict]) -> int:
    """递归统计目录树中的标题数量。"""
    total = 0
    for token in toc_tokens:
        total += 1
        total += count_headings(token.get("children") or [])
    return total


def compute_stats(text: str, toc_tokens: list[dict] | None = None) -> DocStats:
    """根据原文与目录树计算统计信息。"""
    stats = DocStats()
    stats.chars = len(text)
    stats.lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    stats.cjk_chars = len(_CJK_RE.findall(text))
    stats.words = len(_WORD_RE.findall(text))
    stats.headings = count_headings(toc_tokens or [])
    stats.code_blocks = len(re.findall(r"^(?:```|~~~)", text, flags=re.MULTILINE)) // 2
    stats.images = len(re.findall(r"!\[[^\]]*\]\([^)]*\)", text))
    stats.links = len(re.findall(r"(?<!!)\[[^\]]*\]\([^)]+\)", text))
    stats.tables = len(re.findall(r"^\|.*\|$", text, flags=re.MULTILINE))
    stats.reading_minutes = max(
        1, round((stats.cjk_chars + stats.words) / _WORDS_PER_MINUTE)
    )
    return stats


@dataclass
class Document:
    """一次打开的 Markdown 文档。"""

    path: Path
    text: str = ""
    encoding: str = "utf-8"
    stats: DocStats = field(default_factory=DocStats)
    error: str = ""

    @property
    def title(self) -> str:
        """窗口标题优先使用文件名。"""
        return self.path.name or "未命名"

    @property
    def directory(self) -> Path:
        """文档所在目录，用于解析相对图片/链接路径。"""
        return self.path.parent

    @classmethod
    def load(cls, path: str | Path) -> "Document":
        """读取并统计一个文档，读取失败时把错误记录在 :attr:`error` 中。"""
        target = Path(path)
        doc = cls(path=target)
        if looks_binary(target):
            doc.error = f"无法打开：{target.name} 看起来是二进制文件"
            return doc
        try:
            doc.text, doc.encoding = read_text(target)
        except OSError as exc:
            doc.error = f"读取失败：{exc}"
        return doc

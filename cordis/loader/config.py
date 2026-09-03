"""配置文件读取。

支持三种格式，**都不引入新的硬依赖**：

============  ==========================================================
``.json``     :mod:`json`，标准库
``.toml``     :mod:`tomllib`，Python 3.11+ 标准库（只读，正好够用）
``.yml/.yaml`` PyYAML（**可选**），没装时给出明确的报错而不是莫名失败
============  ==========================================================

顶层结构统一是“一份条目列表”，与上游 ``cordis.yml`` 一致::

    # mdviewer.yml
    - id: toc
      name: mdviewer.plugins.toc
    - id: find
      name: mdviewer.plugins.find
      config:
        nocase: true

TOML 没有顶层数组，改用 ``[[plugin]]``，读取时会自动归一化成同一份列表。JSON
两种写法都接受（顶层数组，或 ``{"plugin": [...]}``）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: 读取配置的根键（TOML / 带包裹的 JSON 使用）
ROOT_KEY = "plugin"

SUPPORTED_SUFFIXES = (".json", ".toml", ".yaml", ".yml")


class ConfigError(Exception):
    """配置文件格式或内容不合法。"""


def load_config_file(path: str | Path) -> list[dict[str, Any]]:
    """读取配置文件，返回条目列表。"""
    target = Path(path)
    if not target.is_file():
        raise ConfigError(f"配置文件不存在：{target}")

    suffix = target.suffix.lower()
    if suffix == ".json":
        import json

        data = json.loads(target.read_text(encoding="utf-8"))
    elif suffix == ".toml":
        import tomllib

        data = tomllib.loads(target.read_text(encoding="utf-8"))
    elif suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as error:  # pragma: no cover - 取决于环境
            raise ConfigError(
                f"读取 {target.name} 需要 PyYAML：pip install pyyaml"
            ) from error
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    else:
        raise ConfigError(
            f"不支持的配置文件格式：{suffix}（支持 {' / '.join(SUPPORTED_SUFFIXES)}）"
        )

    return normalize(data, target)


def normalize(data: Any, source: Any = "<config>") -> list[dict[str, Any]]:
    """把各种顶层写法归一化成条目列表。"""
    if isinstance(data, dict):
        data = data.get(ROOT_KEY, [])
    if data is None:
        return []
    if not isinstance(data, list):
        raise ConfigError(f"{source} 的顶层必须是一份条目列表")
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ConfigError(f"{source} 的第 {index + 1} 个条目不是对象：{item!r}")
        raw_id = item.get("id")
        if raw_id is not None and (not isinstance(raw_id, str) or not raw_id.strip()):
            raise ConfigError(
                f"{source} 的第 {index + 1} 个条目的 id 不是非空字符串：{raw_id!r}。"
                "注意 YAML 1.1 会把 on / off / yes / no / true / false 解析成布尔值，"
                '这类 id 需要加引号（id: "off"）。'
            )
        entries.append(dict(item))
    return entries


def find_config_file(base: str | Path, stem: str = "cordis") -> Path | None:
    """在目录下按 json → toml → yml 的顺序找配置文件。"""
    directory = Path(base)
    for suffix in SUPPORTED_SUFFIXES:
        candidate = directory / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


__all__ = ["ROOT_KEY", "SUPPORTED_SUFFIXES", "ConfigError", "find_config_file", "load_config_file", "normalize"]

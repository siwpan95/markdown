"""loader 用到的通用工具。

对应上游 ``packages/loader/src/config/utils.ts``。

上游的 ``evaluate`` 直接 ``eval()`` 一段 JS 表达式（配合 ``with (ctx)``），
Python 侧**刻意不做任意代码求值**——配置文件不是可信输入。这里只提供两类
安全的插值：

* ``{"$env": "VAR_NAME"}``       → ``os.environ["VAR_NAME"]``
* ``{"$env": ["VAR", "默认"]}``  → 取不到时用默认值

``interpolate`` 会递归下钻 dict / list / tuple，保持与上游一致的形状。
"""

from __future__ import annotations

import os
from typing import Any

#: 配置里表示“取环境变量”的键
ENV_KEY = "$env"


def deep_equal(a: Any, b: Any) -> bool:
    """结构化比较（比 ``==`` 宽容：dict / list / tuple 逐项递归）。"""
    if a is b:
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(deep_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(deep_equal(x, y) for x, y in zip(a, b))
    try:
        return bool(a == b)
    except Exception:  # noqa: BLE001
        return False


def is_env_expr(value: Any) -> bool:
    return isinstance(value, dict) and ENV_KEY in value and len(value) == 1


def evaluate_env(spec: Any) -> Any:
    """解析 ``{"$env": ...}``。"""
    if isinstance(spec, (list, tuple)):
        if not spec:
            return None
        name = str(spec[0])
        default = spec[1] if len(spec) > 1 else None
    else:
        name = str(spec)
        default = None
    return os.environ.get(name, default)


def interpolate(value: Any) -> Any:
    """递归替换配置里的 ``{"$env": ...}`` 占位。"""
    if is_env_expr(value):
        return evaluate_env(value[ENV_KEY])
    if isinstance(value, dict):
        return {k: interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(item) for item in value]
    if isinstance(value, tuple):
        return tuple(interpolate(item) for item in value)
    return value


def sort_keys(options: dict[str, Any]) -> dict[str, Any]:
    """把 ``id`` / ``name`` 提到最前、``config`` 放到最后，其余按 key 排序。

    纯粹为了写回配置文件时人类可读，与上游 ``sortKeys`` 一致。
    """
    prepend = ("id", "name")
    append = ("config",)
    head = [(k, options.pop(k)) for k in prepend if k in options]
    tail = [(k, options.pop(k)) for k in append if k in options]
    middle = sorted(options.items(), key=lambda kv: str(kv[0]))
    options.clear()
    options.update(dict(head + middle + tail))
    return options


def diff_keys(new: dict[str, Any], old: dict[str, Any]) -> list[str]:
    """返回两份 options 之间发生变化的键。"""
    keys = set(new) | set(old)
    return sorted(k for k in keys if not deep_equal(new.get(k), old.get(k)))


__all__ = ["ENV_KEY", "deep_equal", "diff_keys", "interpolate", "sort_keys"]

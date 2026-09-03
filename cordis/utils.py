"""Cordis 运行时的底层设施。

对应 TypeScript 版的 ``packages/core/src/utils.ts``。这里只保留 Python 端真正
需要的部分：

* :class:`Symbol` / :data:`symbols` —— 内部状态的键，避免污染服务的公开属性名；
* :class:`DisposableList` —— 有序的 disposer 集合，``push`` 返回“撤销注册”的函数；
* :func:`build_outer_stack` —— 出错时给出更可读的调用栈；
* :func:`is_constructor` / :func:`is_nullable` 等判定工具。
"""

from __future__ import annotations

import inspect
import traceback
from typing import Any, Callable

Disposable = Callable[[], Any]


class Symbol:
    """不带语义的标识，用作内部字典的键。

    Python 没有内建的 ``Symbol``，这里用一个按**对象身份**相等的对象替代
    ——与 JS 的 ``Symbol()`` 一致：每次构造都是新的唯一值。固定 symbol
    （isolate / intercept 等）来自 :data:`symbols` 单例，因此跨模块一致。
    """

    __slots__ = ("_name",)

    #: ``Symbol.for_name()`` 的全局登记表，语义同 JS 的 ``Symbol.for``
    _registry: dict[str, "Symbol"] = {}

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @classmethod
    def for_name(cls, name: str) -> "Symbol":
        """取（或创建）一个全局共享的 symbol —— 等价于 JS 的 ``Symbol.for``。

        需要跨模块指向同一个 key 时用这个（例如 loader 的 ``cordis.entry``
        标记）；直接构造 :class:`Symbol` 则每次都是新的唯一值。
        """
        symbol = cls._registry.get(name)
        if symbol is None:
            symbol = cls(name)
            cls._registry[name] = symbol
        return symbol

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"Symbol({self._name!r})"


class _Symbols:
    """内部 symbol 的命名空间。"""

    _NAMES = (
        "isolate",      # Context.isolate  —— 服务隔离表
        "intercept",    # Context.intercept —— 服务配置覆写表
        "effect",       # 副作用元数据
        "filter",       # 事件过滤函数
        "tracker",      # 服务对象上的追踪信息
        "shadow",       # 派生上下文的影子树
        "init",         # Service 的异步初始化钩子
        "check",        # Service 的可用性判定
        "extend",       # Service 的分叉方法
        "receiver",     # 访问器接收到的上下文
    )

    def __init__(self) -> None:
        for name in self._NAMES:
            object.__setattr__(self, name, Symbol(name))

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return "<cordis.symbols>"


symbols = _Symbols()


class DisposableList(list):
    """按顺序保存 disposer 的列表。

    相比普通 list 多出两个语义：

    * :meth:`push` 返回“把这个元素移除”的函数，便于在 effect 内部自清理；
    * :meth:`clear` 返回被清空的元素（调用方负责逆序执行它们）。
    """

    def push(self, value: Disposable) -> Callable[[], None]:
        list.append(self, value)

        def remove() -> None:
            try:
                list.remove(self, value)
            except ValueError:
                pass

        return remove

    def clear(self) -> list[Disposable]:  # type: ignore[override]
        items = list(self)
        list.clear(self)
        return items

    def delete(self, value: Disposable) -> bool:
        try:
            list.remove(self, value)
        except ValueError:
            return False
        return True


class ChainDict:
    """带原型链的字典。

    Cordis 里 ``isolate`` / ``intercept`` 表都通过 ``Object.create`` 形成原型链，
    子作用域只记录差异。Python 侧用本类表达同样的语义。
    """

    __slots__ = ("_data", "_parent")

    def __init__(
        self, parent: "ChainDict | None" = None, data: dict | None = None
    ) -> None:
        self._parent = parent
        self._data: dict[Any, Any] = dict(data or {})

    def get(self, key: Any, default: Any = None) -> Any:
        node: ChainDict | None = self
        while node is not None:
            if key in node._data:
                return node._data[key]
            node = node._parent
        return default

    def __getitem__(self, key: Any) -> Any:
        node: ChainDict | None = self
        while node is not None:
            if key in node._data:
                return node._data[key]
            node = node._parent
        raise KeyError(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        self._data[key] = value

    def __contains__(self, key: Any) -> bool:
        node: ChainDict | None = self
        while node is not None:
            if key in node._data:
                return True
            node = node._parent
        return False

    def extend(self, data: dict | None = None) -> "ChainDict":
        """派生一份只记录差异的子表。"""
        return ChainDict(self, data)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"ChainDict({self._data!r})"


def is_nullable(value: Any) -> bool:
    """等价于 cosmokit 的 ``isNullable``。"""
    return value is None


def is_constructor(value: Any) -> bool:
    """判断插件是否为“类”形态。"""
    return inspect.isclass(value)


class CordisError(Exception):
    """Cordis 运行时错误。"""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def build_outer_stack(depth: int = 8) -> list[str]:
    """抓取调用点之外的若干层栈，用于拼装错误上下文。"""
    stack = traceback.extract_stack()[:-2]
    frames = [
        f"{frame.filename}:{frame.lineno} in {frame.name}"
        for frame in stack[-depth:]
    ]
    return frames


def compose_error(stack: list[str]) -> Callable[[Exception], None]:
    """把外部调用栈附加到异常的 ``__notes__`` 上（Python 3.11+ 会一并打印）。"""

    def annotate(error: Exception) -> None:
        note = "cordis effect 注册于:\n  " + "\n  ".join(stack)
        notes = getattr(error, "__notes__", None)
        if notes is None:
            try:
                error.__notes__ = [note]  # type: ignore[attr-defined]
            except AttributeError:  # pragma: no cover - 不可变异常
                pass
        else:
            notes.append(note)

    return annotate


def to_disposables(effect: Any) -> list[Disposable]:
    """把 ``effect()`` 的返回值归一化成一组 disposer。

    支持四种形态：

    * ``None`` —— 无副作用；
    * 可调用对象 —— 一个 disposer；
    * 生成器 —— 依次 ``yield`` 多个 disposer（Cordis 的 mixin 就靠这个）；
    * 序列 —— 一组 disposer。

    注意语义：``ctx.effect(fn)`` 是**执行** ``fn`` 并收集它的返回值，不是把
    ``fn`` 本身登记为清理函数。想登记一个现成的清理函数要写成
    ``ctx.effect(lambda: cleanup)``。这里对非可调用项直接报错，避免把
    ``dict.pop()`` 之类的返回值误当成 disposer 而静默出错。
    """
    if effect is None:
        return []
    if callable(effect):
        return [effect]
    if inspect.isgenerator(effect):
        items = list(effect)
    elif isinstance(effect, (list, tuple)):
        items = list(effect)
    else:
        raise TypeError(f"Invalid effect: {effect!r}")
    for item in items:
        if not callable(item):
            raise TypeError(f"Invalid effect: {item!r} is not callable")
    return items


__all__ = [
    "ChainDict",
    "CordisError",
    "Disposable",
    "DisposableList",
    "Symbol",
    "build_outer_stack",
    "compose_error",
    "is_constructor",
    "is_nullable",
    "symbols",
    "to_disposables",
]

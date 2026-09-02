#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""旧入口的兼容包装。

原 ``ma1n.py`` 是一个单文件脚本，现已按职责拆分到 ``mdviewer`` 包中。
这里保留同名文件，避免已有的快捷方式/脚本失效。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mdviewer.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

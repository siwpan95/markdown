#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Markdown Viewer 启动入口。

用法::

    python main.py                     # 启动图形界面
    python main.py README.md           # 启动并直接打开指定文件
    python main.py README.md --to-html out.html
    python main.py --list-backends     # 查看当前环境可用的渲染后端
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许直接以脚本方式运行：把项目根目录加入模块搜索路径
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mdviewer.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

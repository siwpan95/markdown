"""支持 ``python -m mdviewer [文件]`` 方式启动。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

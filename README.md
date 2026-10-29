# Markdown Viewer

## 仓库角色定位（投资组合分级 ②）

> 本仓在 siwpan 投资组合（D:/projects/repos，共 133 仓）中定级为 **② 保留**，领域 **开发者/系统工具**。
> **角色**：内部工具。
> **维护策略**：② 旗舰 / 枢纽仓库打磨保留，作为能力展示或收敛点；② 保留类仓库低优先维持、不主动扩张。
> 投资组合统一分级索引：`D:/projects/repos/PORTFOLIO_TIERING.md`。

一个基于 Tkinter 的本地 Markdown 查看器，**用 Cordis（时空可组合性元框架）
重写了架构**。

项目最初只是一个 40 行的单文件脚本（``ma1n.py``）。2026-09 的重构把它拆成了
四层，其中插件与服务的生命周期、依赖关系、副作用回滚全部交给
[cordiverse/cordis](https://github.com/cordiverse/cordis) 的 Python 移植版
（见本仓库的 ``cordis/`` 目录）管理。

> 本文本身就是一个合法的 Markdown 文档，可以直接用本程序打开查看渲染效果。

---

## 目录

- [架构总览](#架构总览)
- [Cordis 速览](#cordis-速览)
- [声明式装配与热替换](#声明式装配与热替换)
- [功能特性](#功能特性)
- [安装](#安装)
- [使用方式](#使用方式)
- [快捷键](#快捷键)
- [项目结构](#项目结构)
- [扩展指南](#扩展指南)
- [渲染后端](#渲染后端)
- [配置与数据存放位置](#配置与数据存放位置)
- [已知限制](#已知限制)
- [实现说明](#实现说明)
- [测试](#测试)
- [许可证](#许可证)

---

## 架构总览

四层，依赖方向自上而下单向：

```
┌──────────────────────────────────────────────────────────────┐
│  cordis/       Context · Fiber · Service · effect · inject    │
│                时空可组合性运行时（Python 移植，零业务代码）      │
├──────────────────────────────────────────────────────────────┤
│  mdviewer/core/      纯逻辑：配置/主题/文档/渲染/高亮/导出      │
│                      不 import tkinter，CLI 无界面转换只加载它 │
├──────────────────────────────────────────────────────────────┤
│  mdviewer/services/  Cordis 服务（占据稳定的上下文键）          │
│                      settings themes documents renderer       │
│                      backends window                          │
├──────────────────────────────────────────────────────────────┤
│  mdviewer/plugins/   Cordis 插件（一切功能都是插件）            │
│                      viewer shell toc find status appearance  │
│                      auto-reload recent-files exporter        │
│                      + backend_tkinterweb / tkhtmlview / …    │
└──────────────────────────────────────────────────────────────┘
```

装配只发生在一个地方——``mdviewer/app.py`` 的 ``create_context()``，且有两种模式：

```python
ctx = Context()
for service in SERVICE_ORDER:        # 6 个服务 + 3 个后端：始终代码装配
    ctx.plugin(service, config)

for plugin in FEATURE_PLUGINS:       # 模式一：内置默认顺序
    ctx.plugin(plugin)

# 模式二：功能插件改由 loader 按配置文件声明式加载（--config）
ctx.loader.load("cordis.example.yml")
```

除此之外没有任何地方需要知道“系统里装了什么”。插件之间不互相 import，只
通过 ``inject`` 声明依赖、通过 :mod:`mdviewer.events` 里的事件通信。

**重构前后的对照**（同一个 ``README.md``，字节级一致的输出已由测试锁定）：

| | 重构前 | 重构后 |
| --- | --- | --- |
| 主控制器 | ``app.py`` 单文件 623 行，管窗口+菜单+渲染+查找+状态栏+导出 | ``app.py`` 只剩 100 行装配代码 |
| 后端选择 | 工厂函数里 ``if/elif`` 三选一 | 插件注册表 + 优先级探测 |
| 设置联动 | 手工调用 ``settings.save()`` 并同步各控件 | ``settings/change`` 事件广播 |
| 插件卸载 | 不支持 | ``ctx.registry.delete(plugin)`` 完整回滚 |
| 依赖顺序 | 靠代码顺序隐式保证 | ``inject`` 声明，运行时推导 |
| 装配方式 | 代码里写死插件清单 | 代码装配 + **配置文件声明式装配**（`--config`） |
| 改插件代码 | 关掉重启 | **热替换**（`--watch`），失败自动回滚 |

---

## Cordis 速览

Cordis 解决两个正交的问题，合称“时空可组合性”：

**时间可组合性——副作用必须可逆。** 插件注册的每个监听器、每个控件、每个定时
器都返回一个 disposer；Fiber 卸载时按**注册的逆序**调用它们，不留残余。

```python
def apply(ctx, config):
    ctx.on("document/open", handler)          # 监听器随插件卸载自动移除
    ctx.effect(lambda: window.add_pane(...))  # 自定义资源同理
    return lambda: cleanup()                  # 也可以直接返回 disposer
```

**空间可组合性——依赖必须声明。** 插件用 ``inject`` 声明所需服务，服务没就绪时
插件停在 ``PENDING``，就绪后自动激活，服务消失时自动停用。

```python
def apply(ctx, config):
    ctx.documents.open(path)      # 进到这里时 ctx.documents 一定可用

apply.inject = ["settings", "documents"]
```

想读完整个运行时，看 ``cordis/`` 的 12 个文件即可（约 2500 行，含 loader 与
HMR）。这里列出与 TypeScript 上游的**已知差异**，都是语言机制所迫：

| 差异 | 原因 | 位置 |
| --- | --- | --- |
| 用 ``__getattr__`` / ``__setattr__`` 代替 ``Proxy`` | Python 无 Proxy | ``cordis/context.py`` |
| ``ctx.on`` / ``ctx.plugin`` 写成真方法，显式传 ctx | JS 靠 ``this`` 绑定，Python 没有 | ``cordis/context.py`` |
| Fiber 状态机是**同步**的 | Tkinter 事件循环同步，异步会引入重入 | ``cordis/fiber.py`` |
| ``parallel`` 汇总异常而非真并行 | 同上 | ``cordis/events.py`` |
| ``thisArg`` 作为首个位置参数传入 | 无 ``this`` | ``cordis/events.py`` |
| 未移植 ``shadow`` 追踪 | 本项目无多租户隔离需求，``isolate`` 已够用 | ``cordis/context.py`` |
| loader 不支持任意表达式求值（``!!js/expr``） | 配置文件不是可信输入，只保留 ``$env`` 插值 | ``cordis/loader/utils.py`` |
| HMR 用轮询 + 主线程调度，而非 chokidar | 零新依赖；Tkinter 只能在主线程碰控件 | ``cordis/hmr.py`` |

---

## 声明式装配与热替换

上游 Cordis 有配套的 ``@cordisjs/plugin-loader`` 与 ``@cordisjs/plugin-hmr``，
本仓库同样移植了这两件（``cordis/loader/`` + ``cordis/hmr.py``）。

### 用配置文件装配

```bash
python main.py --config cordis.example.yml
```

功能插件的增删启停从此在配置文件里完成——服务与渲染后端仍是代码装配（它们是
平台，不是可选项）。配置支持 ``.yml`` / ``.json`` / ``.toml``：

```yaml
- id: viewer
  name: viewer            # 短名（见 app.py 的 _register_builtins）
- id: find
  name: mdviewer.plugins.find    # 也可以写完整模块路径
  config:
    nocase: true
- id: off
  name: toc
  disabled: true          # 保留配置但停用
- id: ui
  name: cordis:group      # 分组：config 是一份子条目列表，可整体启停
  config:
    - id: toc
      name: toc
```

运行时改配置只重建受影响的子树，其余插件状态原样保留：

```python
ctx.loader.update("toc", {"disabled": True})   # 停用目录侧栏
ctx.loader.update("toc", {"config": {...}})    # 换配置，插件自动重启
ctx.loader.create({"id": "x", "name": "viewer"})  # 运行时新增
ctx.loader.remove("x")                          # 运行时移除
```

配置值支持 ``{"$env": ["VAR", "默认值"]}`` 取环境变量。**刻意不支持任意表达式
求值**。另外注意 YAML 1.1 会把 ``on/off/yes/no`` 解析成布尔值，这类 id 要加
引号（``id: "off"``），loader 检测到非字符串 id 会直接报错而不是静默换名。

### 热替换

```bash
python main.py --watch     # 或与 --config 联用
```

改 ``mdviewer/plugins/*.py``、``mdviewer/services/*.py`` 里的代码，对应的插件
会**在不重启窗口的前提下**被替换：旧 Fiber 的监听器、控件、定时器逆序清理，
新代码以同样的配置重新加载。依赖链上的模块（``from x import y`` 的 ``x``）
也会一起重载。任一步失败都会**回滚**到上一个可用版本，应用始终可用。

线程模型：监听线程发现变化 → 攒够防抖窗口 → ``window.after(...)`` 切回 Tk
主线程执行重载。``--watch`` 默认不开，避免生产误用。

---

## 功能特性

### 文档

- 打开任意 ``.md`` / ``.markdown`` 文件，支持拖拽式的命令行传参
- **自动重载**：文件被外部编辑器保存后自动刷新（可关闭）
- **最近打开**：最近 15 个文件记录在菜单中，失效路径自动剔除

### 渲染

- **代码块语法高亮**（Python / JavaScript / JSON / SQL / Bash … 600+ 种语言）
- **表格、脚注、定义列表、属性列表、缩写、提示块（admonition）**
- **任务列表** ``- [x]`` 显示为 ☑ / ☐
- **删除线** ``~~文本~~``（GFM 风格，Python-Markdown 原生不支持，由本项目补充）
- **相对图片自动解析**：``![图](images/a.png)`` 会按文档所在目录解析成本地绝对路径
- **内部链接跳转**：点击指向其他 ``.md`` 文件的链接，直接在程序内打开

### 阅读辅助

- **目录侧栏**：多级标题树，支持关键字过滤，点击即跳转
- **页内查找**：``Ctrl+F`` 高亮全部匹配项，支持上一个/下一个与忽略大小写
- **明暗主题**：``Ctrl+D`` 一键切换，界面与正文同步换色
- **字号缩放**：``Ctrl+=`` / ``Ctrl+-`` / ``Ctrl+0``
- **自动换行**开关
- **状态栏**：文件路径、编码、字符数、标题数、代码块数、图片数与预计阅读时长

### 导出

- **导出独立 HTML**：自带完整 CSS 与代码高亮样式，双击即可用浏览器打开
- **在浏览器中打开**：生成临时 HTML 并调用默认浏览器，可再打印为 PDF

---

## 安装

```bash
pip install -r requirements.txt
```

依赖非常简单，只有四个包：

| 依赖 | 用途 |
| --- | --- |
| `Markdown` | Markdown 解析 |
| `Pygments` | 代码块语法高亮 |
| `tkhtmlview` | 默认渲染后端 |
| `Pillow` / `requests` | tkhtmlview 的硬依赖（图片解码与网络图片） |

> `tkinter` 属于 Python 标准库，无需安装（部分 Linux 发行版需要额外安装
> `python3-tk` 系统包）。

可选的增强依赖见 `requirements.txt` 末尾的注释说明。

---

## 使用方式

### 启动图形界面

```bash
python main.py                 # 启动后手动选择文件
python main.py README.md       # 启动并直接打开指定文件
```

### 无界面转换

不打开窗口，直接把 Markdown 转成自带样式的 HTML（只加载 ``core`` 层，
不 import tkinter）：

```bash
python main.py README.md --to-html output.html
python main.py README.md --to-html output.html --theme dark --font-size 16
```

### 查看后端与插件

```bash
python main.py --list-backends
python main.py --list-plugins
```

### 声明式装配

用配置文件替代内置的功能插件清单：

```bash
python main.py --config cordis.example.yml
python main.py --config cordis.example.yml --watch   # 附带热替换
```

配置格式见 [声明式装配与热替换](#声明式装配与热替换)。

`--list-backends` 输出示例：

```
  TkinterWeb
* tkhtmlview
  纯文本

当前环境将使用：tkhtmlview（兼容模式）
降级说明：TkinterWeb 不可用（OSError）
```

`--list-plugins` 输出示例：

```
插件                    依赖
------------------------------------------------------------
backend/tkinterweb    backends, window
viewer                settings, themes, documents, renderer, backends, window
shell                 settings, documents, themes, backends, window
```

### 以模块方式运行

```bash
python -m mdviewer README.md
```

---

## 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl+O` | 打开文件 |
| `F5` | 重新加载当前文件 |
| `Ctrl+F` | 页内查找 |
| `Ctrl+E` | 导出为 HTML |
| `Ctrl+B` | 在浏览器中打开 |
| `Ctrl+D` | 切换明暗主题 |
| `Ctrl+T` | 显示 / 隐藏目录 |
| `Ctrl+=` / `Ctrl+-` | 放大 / 缩小字号 |
| `Ctrl+0` | 重置字号 |
| `Esc` | 关闭查找栏 |
| `Ctrl+Q` | 退出 |

---

## 项目结构

```
markdown/
├── main.py                      启动入口
├── ma1n.py                      旧入口的兼容包装
├── requirements.txt
├── README.md
│
├── cordis/                      ★ Cordis 运行时（Python 移植）
│   ├── context.py               服务容器 / 插件作用域
│   ├── fiber.py                 生命周期状态机 + 副作用栈
│   ├── registry.py              插件注册表
│   ├── reflect.py               服务注册与依赖解析
│   ├── events.py                emit / serial / bail / parallel / waterfall
│   ├── service.py               服务基类
│   ├── logger.py
│   ├── utils.py                 Symbol / DisposableList / ChainDict
│   ├── hmr.py                   模块热替换（依赖分析 / 原子回滚）
│   └── loader/                  声明式装配（Entry / Group / Tree / Loader）
│
├── mdviewer/
│   ├── __init__.py              包入口（延迟导入 tkinter）
│   ├── __main__.py              支持 python -m mdviewer
│   ├── cli.py                   命令行参数解析
│   ├── app.py                   ★ 装配器：把服务与插件装进 Context
│   ├── events.py                事件名契约（集中管理，避免字符串漂移）
│   ├── core/                    纯逻辑，不依赖 Tk
│   │   ├── config.py            常量与用户设置持久化
│   │   ├── document.py          文件读取（编码探测）与统计
│   │   ├── theme.py             主题配色（CSS 与受限内联样式）
│   │   ├── highlight.py         自研的 Pygments 代码块高亮扩展
│   │   ├── renderer.py          Markdown → HTML，rich / simple 两档
│   │   └── exporter.py          导出独立 HTML
│   ├── services/                Cordis 服务
│   │   ├── settings.py          ctx.settings
│   │   ├── theme.py             ctx.themes
│   │   ├── documents.py         ctx.documents
│   │   ├── renderer.py          ctx.renderer
│   │   ├── backends.py          ctx.backends（后端注册表）
│   │   └── window.py            ctx.window（窗口骨架与资源申请）
│   ├── plugins/                 Cordis 插件
│   │   ├── viewer.py            文档 → 渲染 → 后端的串联
│   │   ├── shell.py             菜单 / 工具栏 / 快捷键
│   │   ├── toc.py               目录侧栏
│   │   ├── find.py              页内查找
│   │   ├── status.py            状态栏
│   │   ├── appearance.py        主题 / 字号 / 后端切换的界面表现
│   │   ├── auto_reload.py       文件变化自动重载
│   │   ├── recent_files.py      最近打开列表
│   │   ├── exporter.py          导出 HTML / 浏览器打开
│   │   ├── hmr.py               开发期热替换（--watch 才注册）
│   │   └── backend_*.py         三个内置渲染后端
│   ├── backends/                后端实现（Base + 三个具体后端）
│   └── widgets/                 目录 / 查找 / 状态栏控件
│
├── cordis.example.yml           声明式装配的示例配置
│
├── tests/
│   ├── test_cordis.py           Cordis 运行时单测（29 项，无 Tk 依赖）
│   ├── test_loader.py           loader / HMR 测试（28 项，含真实热替换）
│   └── test_viewer.py           应用冒烟测试（31 项，含基线逐字节比对）
│
├── cordis-main/                 上游 TypeScript 实现（参考，不参与构建）
└── paper-main/                  《A Programming Paradigm for Spatiotemporal
                                  Composability》论文 PDF（参考）
```

---

## 扩展指南

### 加一个功能

写一个函数，声明依赖，订阅事件，返回 disposer（可选）:

```python
# mdviewer/plugins/word_count.py
from .. import events

def apply(ctx, config=None):
    def on_rendered(result):
        print("渲染完成，标题数：", len(result.toc_tokens))

    ctx.on(events.DOC_RENDERED, on_rendered)

apply.name = "word-count"
apply.inject = ["documents"]
```

然后在 ``mdviewer/plugins/__init__.py`` 的 :data:`FEATURE_PLUGINS` 里加一行。
不需要改动任何既有文件。

如果走配置文件装配，还可以把它登记成短名（``mdviewer/app.py`` 的
``_register_builtins``），之后配置里写 ``name: word-count`` 即可启用——
配合 ``--watch``，改插件代码立即生效，这就是最顺的开发循环。

想给菜单加条目，订阅 ``menu/file`` / ``menu/view`` / ``menu/help`` 事件：

```python
def on_menu_view(menu):
    menu.add_command(label="统计", command=show_stats)

ctx.on(events.MENU_VIEW, on_menu_view)
```

### 加一个渲染后端

实现 :class:`~mdviewer.backends.base.Backend` 接口，再写一个注册插件：

```python
# mdviewer/plugins/backend_mine.py
def apply(ctx, config=None):
    from .. import events
    from ..backends.mine import MyBackend

    def factory(_ctx, theme, font_size):
        return MyBackend(
            ctx.window.content, theme, font_size,
            on_link=lambda t: ctx.emit(events.LINK_OPEN, t),
        )

    ctx.backends.register(
        MyBackend.key, MyBackend.label, factory,
        priority=15,                       # 数字越小优先级越高
        supports_css=MyBackend.supports_css,
        menu_label="我的后端",
    )

apply.name = "backend/mine"
apply.inject = ["backends", "window"]
```

注册进 :data:`BACKEND_PLUGINS` 即可，探测/降级逻辑自动生效。

### 运行时卸载插件

```python
from mdviewer.plugins import toc
ctx.registry.delete(toc)     # 目录面板、它的监听器、注册项全部消失
```

---

## 渲染后端

不同环境下可用的 HTML 渲染能力差别很大，因此程序内置了三个后端，
启动时按 ``priority`` 依次探测，任何一个不可用都会静默降级：

| 后端 | 依赖 | 能力 | 备注 |
| --- | --- | --- | --- |
| `tkinterweb` | `tkinterweb` | 完整 CSS 2.1，表格/引用/提示块表现最好 | 需要 Tcl/Tk 8.6；**Tcl/Tk 9 下无法使用** |
| `tkhtmlview` | `tkhtmlview` | 受限 HTML，仅支持 6 个内联样式属性 | 默认后端，兼容性最好 |
| `plaintext` | 无 | 只读显示 Markdown 源码 | 兜底方案 |

可以在 **视图 → 渲染后端** 菜单中手动指定，选择 `自动` 时按上表顺序探测。

> **为什么 Tcl/Tk 9 用不了 TkinterWeb？**
> TkinterWeb 依赖 Tkhtml，而其预编译二进制只提供到 Tcl/Tk 8.6。
> Python 3.13+（含本机的 Python 3.14）自带 Tcl/Tk 9.0，此时创建控件会抛出
> `OSError: No Tkhtml versions could be found for Tcl/Tk 9`。
> 程序会捕获该异常并自动回退到 `tkhtmlview`，状态栏会显示降级原因。

> **多标签页**：Tkhtml 与 `ttk.Notebook` 在 64 位 Windows 上存在已知冲突，
> 因此本项目不使用多标签，一次只显示一个文档。

---

## 配置与数据存放位置

| 内容 | 路径 |
| --- | --- |
| 用户设置 | `~/.mdviewer/settings.json` |
| 浏览器预览临时文件 | `~/.mdviewer/preview/` |

Windows 下 `~` 即 `%USERPROFILE%`。设置 `MDVIEWER_HOME` 环境变量可改变该目录，
便于做成便携版（测试也用它做隔离）。

`settings.json` 中的字段：

```json
{
  "theme": "light",              // light | dark
  "backend": "auto",             // auto | tkinterweb | tkhtmlview | plaintext
  "base_font_size": 14,          // 8 ~ 36
  "show_toc": true,
  "auto_reload": true,
  "word_wrap": true,
  "window_geometry": "1100x720",
  "recent_files": []
}
```

所有写入都经过 ``SettingsService.update()``：它会逐项比对，只在真正变化时
落盘并广播 ``settings/change``，因此不会出现重复保存或通知风暴。

---

## 已知限制

- **不支持 JavaScript 渲染的图表**：Mermaid 流程图、MathJax/Katex 数学公式都依赖 JS，
  Tkhtml 与 tkhtmlview 均不执行脚本，相关内容会显示为源码。
- **表格在默认后端下没有边框**：tkhtmlview 用制表符模拟列，只能保证对齐。
  需要表格边框时请在浏览器中打开，或使用支持 CSS 的 `tkinterweb` 后端。
- **嵌套引用块**：默认后端只处理最外层 `blockquote`，嵌套层级会被展平。
- **超大文档**：为保证响应速度，超过 20 万字符的单个代码块会跳过着色。
- **HMR 依赖图是近似的**：依赖关系从字节码里的 `IMPORT_NAME` / `IMPORT_FROM`
  提取（因为 Python 不暴露 ESM 那样的模块链接表），函数体内的动态
  ``importlib.import_module(...)`` 识别不到；改这类文件不会自动触发依赖方重载，
  需要手动 `ctx.hmr.reload_plugin(...)`。

---

## 实现说明

记录几个不太直观、但直接影响实现方式的结论。

### 1. 为什么自己写代码块高亮扩展

`codehilite` 只处理**缩进代码块**和 `:::lang` 形式的围栏块，而绝大多数 Markdown
使用的是 ` ```lang ` 围栏；负责围栏的 `fenced_code` 又只输出
`<pre><code class="language-python">`，不会调用 Pygments。
二者组合的结果是——**代码高亮根本不生效**。

因此 `mdviewer/core/highlight.py` 实现了一个 `Postprocessor`，在最终 HTML 上识别
`<pre><code>` 并调用 Pygments 重新着色。注册优先级设为 `5`，确保晚于
`raw_html(30)` 与 `amp_substitute(20)` 执行，拿到的是还原后的真实代码文本。

### 2. 为什么有两种输出档位

`tkhtmlview` 并不是浏览器内核，它用 `html.parser` 把 HTML 翻译成 `Text` 的 tag，
而且是**不解析 `<style>` 样式表**的——CSS 文本会被当成正文显示出来。
它只认 `color` / `background-color` / `font-family` / `font-size` /
`text-align` / `text-decoration` 这六个内联属性。

所以渲染器提供两个档位：

- `rich`：标准 HTML + 外置 CSS，给 `tkinterweb` 与导出的 HTML 用；
- `simple`：全部样式内联，并把 `blockquote` / `hr` / `del` / `admonition`
  等它不认识的标签降级成带样式的 `div` / `span` / 字符。

### 3. 深色主题下的“黑底黑字”

`tkhtmlview` 在其模块级常量 `DEFAULT_STACK` 中把默认前景色硬编码为 `black`，
且会给每个元素显式赋上该值，导致单纯配置 `Text` 的 `foreground` 无效。
后端在每次渲染前会改写该常量，并同时按倍率改写标题字号常量以实现整体缩放。

### 4. 图片路径

- `tkhtmlview` 用 `os.path.exists(src)` 判断图片，因此 `file://` 协议无效，
  必须给它**本机绝对路径**；
- `tkinterweb` 与浏览器则需要 `file://` URI。

渲染器按档位分别输出这两种形式。

### 5. 编码探测

读取文件时按 `utf-8-sig → utf-8 → gb18030 → big5 → utf-16 → latin-1`
依次尝试，覆盖国内最常见的编码情况，实际使用的编码会显示在状态栏。

### 6. 为什么 `ctx.effect` 要写成 `lambda: cleanup` 而不是 `lambda: cleanup()`

`ctx.effect(execute)` 会**执行** `execute` 并把它的**返回值**登记为 disposer。
写成 `lambda: widget.destroy()` 会当场销毁控件——这是移植过程中真实踩到的坑，
因此 `cordis/utils.py::to_disposables` 对非可调用的返回值直接抛 `TypeError`，
而不是静默忽略。

---

## 测试

```bash
python -m unittest discover -v          # 全部 88 项
python -m unittest tests.test_cordis -v # 只要 Cordis 运行时（无 Tk 依赖）
python -m unittest tests.test_loader -v # loader / HMR（含真实热替换，无 Tk）
python -m unittest tests.test_viewer -v # 应用冒烟测试（真实 Tk 窗口）
```

`tests/test_loader.py` 里的 HMR 用例是真的在改磁盘上的文件：写坏代码 → 观察
回滚、修好 → 观察恢复、连换三次 → 断言监听器数量不涨（无泄漏）。等待逻辑是
事件驱动的（轮询 ``reload_count`` 而非死睡固定时长），因此不依赖机器快慢。

`tests/test_viewer.py` 会跑真实的 Tk 窗口。所有与内容相关的期望值锚定在
`tests/fixtures/sample.md`（**改它需要重新采集基线**），而不是 `README.md`
——文档会改，基线不该跟着漂。

| 基线项 | 期望值 |
| --- | --- |
| 后端 | `tkhtmlview`，降级说明含 `TkinterWeb 不可用（OSError）` |
| 编码 | `utf-8-sig` |
| 文档统计 | `467 字符 · 195 词 · 8 标题 · 1 代码块 · 0 图片 · 约 1 分钟` |
| 目录标题数 | 8 |
| 查找 “渲染” | 4 处命中 |
| 导出 light (14px) | 9659 字节，sha256 前 16 位 `363c3dcaabe175e1` |
| 导出 dark (16px) | 9164 字节，sha256 前 16 位 `2bdf145217e3c84c` |

**重构前后的等价性**是单独验证的：重构前先采集了同一个 `README.md` 的
`--list-backends` 输出、文档统计与两份导出文件的 sha256，重构后逐字/逐字节比对，
全部一致（light = `594120d8…` / 23404 字节，dark = `7c03777c…` / 22909 字节）。

测试用 `MDVIEWER_HOME` 指向临时目录（每个用例一个），不会碰到真实设置；
`messagebox` 被替换成空实现，避免弹窗阻塞。

---

## 许可证

MIT

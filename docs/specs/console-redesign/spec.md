# 控制台三栏科幻工作台改造规格

版本：1.1 · 状态：待实现
范围：`ui/src/`、构建产物 `ui/index.html`、`src/panweb/commands.py`（新增）、
`src/panweb/ui_actions.py`（新增只读解析路由）、`src/panweb/entries.py`（节点健康字段）。
不在范围：`share.py`、`proxy.py` 分享页渲染、`publish.py`、`cli_commands.py`
（后两者已接近/达到 500 行，本次不改）。

## 1. 目标与验收口径

把默认页从「侧栏 + 卡片堆叠」改为固定三栏工作台：

| 栏位 | 角色 | 必须可见 |
| --- | --- | --- |
| 左栏 | 历史与资产 | 应用列表、状态、搜索、选中项时间线 |
| 中栏 | 对话式发布 | 指令输入、实时步骤、成功回执/失败重试 |
| 右栏 | 进程可视化 | 代理/隧道/源应用节点、PV、访客、网址、隧道重建次数 |

验收不是「截图好看」：必须真起控制台、真发布一条静态站点、真停止，并验证
对话步骤、回执、右栏状态随 `/api/state` 变化；全量测试、构建检查、ruff 全绿。

## 2. 布局与 DOM 契约

### 2.1 桌面（≥901px）

`ui/src/index.html` 变成四段式 shell：

```
body
├── aside.rail#asset-rail        // 左栏：品牌、搜索、资产列表、时间线、环境、许可
├── main.main#top                // 中栏：顶栏导航 + 五个 .page
└── aside.viz#viz-rail           // 右栏：进程可视化（仅工作台页显示）
```

- 左栏宽度变量 `--rail-w`（默认 300px，可拖动 240–420px，双击复位）。
- 右栏宽度变量 `--viz-w`（默认 324px，可拖动 280–420px，双击复位）。
- 中栏 `flex: 1; min-width: 0;`，内部不再有独立侧栏。
- `body[data-page]` 控制栏目显隐：
  - `apps`：三栏全显；
  - `feed/agents/system`：右栏 `display:none`，左栏保留（资产上下文仍可切回工作台）；
  - `term`：左栏与右栏都收起，终端占满中栏。
- 全局导航 `工作台 / 动态与提醒 / 连接 Agent / 终端 / 系统与数据` 放进中栏顶栏，
  使用 `[data-page]` 标签，保留原有 `switchPage()` 行为。
- 顶栏动作保留：环境 pill、通知铃、刷新、`高级发布`（原发布弹窗入口）、
  移动端 `资产`/`进程` 抽屉按钮。
- 移除亮/暗主题按钮；`<html data-theme="dark">` 固定深色。

### 2.2 左栏 DOM

- `#asset-search`：内存过滤 `STATE.apps` + `STATE.hosted`，不新增后端搜索。
- `#asset-list`：每条 `data-id`，状态点 `online/offline/expired/hosted`，
  显示名称、类型/端口、PV、到期剩余；点击选中并同步中/右栏。
- `#asset-timeline`：选中项变更时间线，读 `/api/history?id=&limit=20`；
  事件类型沿用 `events.EVENT_TYPES`：发布、重启、换网址、改口令、到期、停止、出错。
- `#asset-empty`：无应用时显示「还没有发布」+「高级发布」按钮。
- 底部署环境、cloudflared 版本、数据目录、许可按钮沿用现有文案与函数。

### 2.3 中栏 DOM

`partials/pages.html` 的 `#page-apps` 改为：

```
.topbar          // 导航 + 动作
.workbench
├── .conv-log#chat-log        // 消息流
└── .conv-composer
    ├── #cmd-input           // textarea/input，Enter 执行，Shift+Enter 换行
    ├── #cmd-run             // 执行按钮
    └── .cmd-hints           // 可点击示例
```

- 空状态：欢迎消息 + 三条示例指令（发布 3000 / 发布 <文件夹> / 停止 8080）。
- 消息类型：`user`、`step`、`success`、`error`、`system`。
- 成功消息内包含：网址、分享链接（有则显示）、本地二维码、复制/打开按钮。
- 失败消息内包含：错误原因、可操作提示、`重试`、必要时`打开高级发布`。
- 原有 `#empty-hero`、`#apps-wrap`、`#apps-grid` 从工作台移除；
  其功能由左栏资产列表 + 详情抽屉承担，`core.js` 不再引用这些 ID。
- 其他页（feed/agents/term/system）的现有 DOM 原样保留。

### 2.4 右栏 DOM

`#viz-rail` 内：

- `#viz-empty`：未选中时显示「从左侧选择一个资产」；不画假拓扑。
- `#viz-panel`：
  - `#viz-name` / `#viz-status` / `#viz-url`；
  - `#viz-nodes`：三个 `.viz-node`（`data-node=proxy|tunnel|source`），
    每个含状态点、名称、详情、`online/offline/unknown/disabled` class；
  - `.viz-links` 两条 SVG/CSS 连线，仅两端 `online` 时加 `flow`；
  - `#viz-pv` / `#viz-uv` / `#viz-last` / `#viz-rebuilds` / `#viz-visitors`。
- 节点字段缺失一律显示「未知」，禁止随机数或假心跳。

## 3. 数据来源与刷新

| 数据 | 来源 | 频率 |
| --- | --- | --- |
| 环境、应用列表、PV、最近访客、通知、许可 | `GET /api/state` | 沿用 4 秒，不新增高频轮询 |
| 选中项时间线 | `GET /api/history?id=&limit=20` | 选中变化、发布/停止完成后 |
| 发布默认值（选项合并） | `POST /api/command` 内部读取 `load_publish_defaults()` | 每次指令 |
| 指令解析 | `POST /api/command`（只解析） | 每次指令 |
| 发布/文件夹/启动 | `POST /api/publish|pages|run`，`async:true` + `GET /api/job?id=` | job 700ms 轮询 |
| 停止/自检 | `POST /api/stop`、`POST /api/check` | 指令触发 |
| 节点存活 | `/api/state` 的 `apps[].nodes` | 随 4 秒刷新 |

右栏不新增轮询；`updateViz()` 由 `refresh()` 调用，`refresh()` 仍由 `boot.js` 的
`setInterval(..., 4000)` 驱动。

## 4. 后端契约

### 4.1 `src/panweb/commands.py`（新增，纯解析）

公开 API：

```python
MAX_COMMAND_LEN = 200
def parse_command(text, defaults=None) -> dict
```

成功返回：

```python
{
  "ok": True,
  "verb": "publish" | "run" | "stop" | "check" | "help",
  "action": "publish" | "pages" | "run" | "stop" | "check" | "help",
  "port": int | None,
  "folder": str | None,
  "id": str | None,
  "scope": "all" | "current" | None,
  "options": {"pin": str | None, "expires": str | None,
              "share": bool, "name": str | None},
  "examples": [...],          # 仅 help/错误路径
}
```

失败返回：

```python
{"ok": False,
 "error": {"type": "invalid_command" | "risky_port",
           "message": "...", "hint": "..."},
 "examples": ["发布 3000", "发布 /path/to/dist", "停止 8080", "帮助"]}
```

实现规则：

- 先 `strip()`；长度 >200 → `invalid_command`；含换行/控制字符或
  `; | & $ > < \`` → `invalid_command`（不做 shell 执行）。
- 用 `shlex.split(posix=True)` 分词；分词失败 → `invalid_command`。
- 动词别名：
  - `发布` / `publish` → `publish`
  - `启动` / `run` → `run`
  - `停止` / `stop` → `stop`
  - `检查` / `check` → `check`
  - `帮助` / `help` → `help`
- 目标判定（第一个非选项词）：
  - 纯数字 → 端口，必须 1–65535，否则 `invalid_command`；
  - 以 `/`、`~`、`.` 开头或含 `/` → 文件夹；
  - `全部`/`all` → `scope="all"`（仅停止/检查）；
  - `当前`/`current` → `scope="current"`（仅停止/检查）；
  - 其余字符串 → 视为 id/名称（仅停止/检查），否则发布/启动路径报错。
- 选项键别名：
  - `pin`
  - `有效期` / `expires`
  - `分享` / `share`
  - `名称` / `name`
- 选项值：
  - `pin` 4–32 字符，否则 `invalid_command`；
  - `有效期` 只接受 `1h` / `1d` / `7d` / `永久` / `forever` / `none`，
    `永久` 归一为 `""`；
  - `分享` 接受 `开/关/on/off/true/false`；
  - `名称` ≤80 字符。
- 缺省合并：
  - `port` / `folder` / `id` 缺省为 `None`，由 `core_publish` / `core_pages` /
    `core_run` 的既有默认值处理（上次端口 / 当前目录），UI 不再猜。
  - `share` 缺省取 `defaults.get("share", True)`。
  - `expires` 缺省取 `defaults.get("expires") or ""`。
  - `name` / `pin` 缺省为 `None`。
- 高风险端口：若解析出端口且 `runtime.RISKY_PORTS.get(port)` 非空，返回
  `risky_port`，message 带端口与风险描述，hint 指向「高级发布」勾选风险确认；
  不产生发布动作。
- `help` 返回可用动词与示例。
- 不读取文件、不执行命令、不写状态、不把口令写进 message/hint。

### 4.2 `/api/command`（`ui_actions.py`）

```python
if path == "/api/command":
    result = parse_command(body.get("text") or "", load_publish_defaults())
    if not result.get("ok"):
        return handler.send_json({"ok": False, "error": result["error"]}) or True
    return handler.send_json({"ok": True, "data": result}) or True
```

- 只解析，不执行；沿用 `ui_server` 的 Host/Origin 与 `application/json` 校验。
- 响应不含 `raw` 字段；`options.pin` 只为前端下一步调用发布接口所需，
  前端不得写入 `localStorage` / 消息文本。
- 新增测试放在 `tests/test_commands.py` 与 `tests/test_ui.py` 末尾，避免单文件超 320 行。

### 4.3 节点健康（`entries.py`）

新增：

```python
def entry_nodes(entry) -> dict:
    return {"tunnel": {...}, "proxy": {...}, "source": {...}}
```

每个节点：

```python
{"state": "online" | "offline" | "unknown" | "disabled",
 "detail": "cloudflared 隧道运行中" | "端口 3000 未监听" | ...}
```

语义：

| 节点 | 判定 |
| --- | --- |
| tunnel | `pid` 存在且 `pid_alive(pid)` → online；`pid` 存在但不存活 → offline；`pid` 缺失 → unknown |
| proxy | `proxy_port` 缺失 → disabled（detail：未启用，直连发布）；`server_pid` 缺失 → unknown；`pid_alive(server_pid)` 且 `port_listening(proxy_port)` → online；否则 offline |
| source | `kind=port`：`target` 是合法整数且 `port_listening(target)` → online，否则 offline；`kind=pages`：`os.path.isdir(target)` → online，否则 offline；target 缺失 → unknown |

`core_list()` 对每个条目追加 `e["nodes"] = entry_nodes(e)`。不新增网络探测，
不改变 `entry_alive()` 现有语义。

## 5. 指令语法（用户可见）

```
发布 [端口 | 文件夹] [pin=xxxx] [有效期=1h|1d|7d|永久] [分享=开|关] [名称=xxx]
启动 [文件夹] [同上选项]
停止 [全部 | 端口 | id | 当前]
检查 [端口 | id | 当前]
帮助
```

示例：

```
发布 3000
发布 3000 pin=1234 有效期=1d 分享=开 名称=演示站
发布 ~/Documents/site
发布 /Users/me/project/dist pin=abcd
启动 ~/project
停止 8080
停止 当前
停止 全部
检查 当前
帮助
```

- 省略端口/文件夹时走 core 既有默认值，UI 不另写猜测。
- 解析失败只回一句可操作提示 + 示例，不调用任何发布接口。
- 高风险端口在指令路径直接拒绝，不绕过风险确认。

## 6. 中栏执行与消息流

`ui/src/js/commands.js`：

- `submitCommand()` → `POST /api/command`.
- `executeParsed(parsed)` 按 `action` 分派：
  - `publish`：`/api/publish`，body `{port, name, pin, expires, share, async:true}`；
  - `pages`：`/api/pages`，body `{folder, name, pin, expires, share:true, async:true}`；
  - `run`：`/api/run`，body `{folder, name, pin, expires, share, async:true}`；
  - `stop`：`/api/stop`，body `{target}`；`scope=all` → `"all"`；
    `scope=current` → 当前选中 id；端口 → 由 `STATE.apps` 找同端口条目 id，
    找不到则回「没有发布在端口 X 的应用」；
  - `check`：`/api/check`，body `{id}`；端口/当前同样先解析成 id；
  - `help`：本地渲染帮助，不发请求。
- job 轮询：每 700ms `GET /api/job?id=`；只在 `job.step` 变化时追加一条
  `step` 消息；`done && ok` 追加成功回执；`done && !ok` 追加失败消息。
- 成功回执：
  - 网址（`result.url`）、分享链接（`result.share_url`，有则显示）；
  - 二维码：用内置 `window.qrcode` 生成 SVG，不依赖外链；
  - 按钮：复制网址、打开、停止该应用。
  - 发布完成后 `refresh(true)`、选中新条目、刷新左栏时间线与右栏。
- 失败回执：
  - `error.message` + `error.hint`；
  - `重试` 重新执行同一份已解析指令（仅在内存中保留 `pin`）；
  - `risky_port` 额外提供「打开高级发布」。
- 用户消息回显前把 `pin=xxx` 替换为 `pin=••••`；消息流中永不显示真实口令。
- 执行中禁用输入与发送按钮；完成后恢复。

## 7. 右栏可视化

`ui/src/js/viz.js`：

- `renderViz()` 读取当前选中条目（`STATE.apps` 内）：
  - 节点 class 只由 `nodes.*.state` 驱动；
  - `tunnel/proxy/source` 三节点按 `proxy → tunnel → source` 排列；
  - 连线 `.flow` 仅当相邻两端都 `online`；
  - PV/UV 来自条目 `pv`；最近访客来自 `STATE.visits_recent` 按 name 过滤；
  - 当前网址来自条目 `url` / `share_url`；
  - 隧道重建次数来自 `/api/history` 缓存中 `type in ("restart","url_change")`
    的计数，显示「未知」直到时间线返回。
- 无选中项：`#viz-empty` 显示提示，`#viz-panel` 隐藏。
- `/api/state` 失败：保留上一帧并将节点全部改为 `unknown`，页面顶部提示。
- 不新增 poll；`refresh()` 调用 `renderViz()`。

## 8. 视觉与动效清单

- 固定深色：`#05080d` 背景，冷青/冰蓝霓虹（`--neon: #57e6ff`、
  `--neon-2: #7c9cff`），等宽字体用于 URL/端口/时间。
- 细网格 + 极淡扫描线：`repeating-linear-gradient` 叠加在 `body::before`，
  `pointer-events:none`，不遮挡文字。
- 面板：`background: rgba(10,18,28,.72)`、1px 冷色边框、克制 `box-shadow` 辉光。
- 动效：
  - `.viz-node.online` 呼吸（`box-shadow` + `opacity`，2.6s）；
  - `.viz-link.flow` 虚线流动/渐变扫过（3.4s）；
  - 新消息 `fade-rise`（0.28s）；
  - 执行中步骤点闪烁；
  - 扫描线极慢平移（60s）。
- 所有动效纯 CSS / 原生 JS；不新增依赖/CDN。
- `@media (prefers-reduced-motion: reduce)` 关闭呼吸、流动、扫描线、消息入场。
- 不做的：满屏发光噪点、持续高频闪烁、随机假脉冲。

## 9. 响应式与降级

- `≤900px`：
  - 单栏；左栏 `position:fixed` 抽屉，`body.rail-open` 打开；
  - 右栏 `position:fixed` 底部抽屉，`body.viz-open` 打开；
  - 顶栏 `#assets-toggle` / `#viz-toggle` 可见；
  - 按钮/点击区 ≥48px，输入字号 16px（防 iOS 缩放）；
  - 顶栏标签横向滚动，`overflow-x:auto`，页面无横向溢出。
- 390×844 实测无横向滚动；对话输入常驻底部。
- `/api/state` 未返回：右栏「读取中/未知」，不显示绿色在线。
- 无 JS：保留静态标题与「需要启用 JavaScript」提示（现有 `index.html` 已覆盖）。
- 终端页：左右栏收起，xterm 全幅。

## 10. 安全边界（不得放宽）

- 控制台仍只绑 `127.0.0.1`；Host/Origin、`application/json` 校验不变。
- 路径与 dotfile 拒绝、PIN 不落盘、口令不进分享页 HTML 均沿用现有实现。
- `/api/command` 只解析；不执行、不读任意文件、不返回 `raw`。
- 左栏搜索只过滤内存 `STATE.apps`，不引入后端搜索。
- 指令路径拒绝高风险端口，不能绕过风险确认。
- 前端不把 PIN 写入 `localStorage` / `sessionStorage` / 对话消息文本。

## 11. 验证步骤

1. `python3 -m unittest discover -s tests`：基线 313 项全绿，新增用例全绿。
2. `python3 tools/build_ui.py --check`：通过；不一致则重新构建。
3. `ruff check --select E9,F63,F7,F82 src tools tests`：通过。
4. 真机验收：
   - 临时 `PANWEB_HOME` + `PANWEB_LICENSE_OFF=1` 启动控制台；
   - 起一个本地静态站点，输入 `发布 /tmp/...`；
   - 观察步骤消息、成功回执、右栏节点脉冲；
   - `停止 <端口或当前>` 后确认状态与时间线更新；
   - 输入非法指令确认不产生任何发布。
5. 截图到 `docs/screenshots/console-redesign/`：
   - 1440×900：三栏总览、对话发布中、右栏进程细节；
   - 390×844：单栏总览、左栏抽屉、底部进程抽屉。

## 12. 提交计划

按主题、只 add 具体文件，不 push、不推 tag：

1. 布局骨架：`ui/src/index.html`、`partials/pages.html`、`manifest.json`、
   `styles/console.css`、`styles/scifi.css`、`ui/index.html`
2. 左栏：`js/workbench.js`、相关 CSS
3. 中栏：`src/panweb/commands.py`、`tests/test_commands.py`、
   `ui_actions.py`、`js/commands.js`、相关测试
4. 右栏：`entries.py`、`js/viz.js`、相关测试
5. 移动端与动效微调：CSS/JS 收尾
6. 截图：`docs/screenshots/console-redesign/*.png`

## 13. 已知取舍与残余风险

- 指令不覆盖标题/说明/云端托管，仍走「高级发布」。
- 高风险端口指令直接拒绝，需要风险确认时用高级发布。
- 右栏为 4 秒粒度，不是毫秒级实时；PV 来自聚合数据，最近访客来自内存快照。
- 窄屏单栏下不能同时看时间线与拓扑，需要抽屉切换。
- `nodes` 只反映进程/端口存在性，不代表应用业务健康；业务健康仍靠自检。

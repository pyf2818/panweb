# F1 分享页 2.0 规格

结论：分享页已有模板与状态槽位（在线/有效期/口令），本轮只补「标题、说明」的录入、校验、渲染与 CLI 二维码；不改 `store.py` 事件流、不改 MCP、不做 F2/F3。

## 现状校正

| 位置 | 现状 |
|---|---|
| `share.build_share_page` | 已读 `entry["name"]` / `entry["desc"]`，有默认说明、在线/过期/口令 chip；但标题只认 `name`，`desc` 无长度/控制字符约束 |
| `publish._publish_port` / `core_publish` / `core_pages` / `core_run` | 只收 `name`，没有任何 title/desc 参数；`desc` 只能从控制台 `/api/share` 事后补 |
| `ui_actions._share` | 自行用正则替换控制字符并截断 120，与 CLI 没有共用校验 |
| `cli.py` | `publish/pages/run` 无 `--title` / `--desc` / `--qr` |
| `ui/src/partials/overlays.html` + `publish.js` | 发布弹窗只有「应用名称」，没有标题/说明 |
| `ui/src/js/core.js` / `apps.js` | 卡片与详情只显示 `name`；没有 `title` 回退 |
| 二维码 | 控制台已有 `ui/vendor/qrcode.js`；后端无纯本地二维码能力，CLI 无 `--qr` |

## 设计决策

### 1 数据模型与输入校验

- 条目新增两个可选字段：`entry["title"]`、`entry["desc"]`。不改 `store.py` 结构、不迁移旧条目。
- 新增 `models.entry_title(entry)`：`title` 去空白后非空则返回它，否则回退 `name`，再回退 `"panweb"`。
- 新增 `publish.normalize_title(value)` / `publish.normalize_desc(value)`：
  - `None` / 空串 → `None`（不落库，保持默认外观）；
  - 含 `\x00-\x1f`、`\x7f`（含换行/制表符）→ `PanwebError(2, "invalid_argument")`；
  - 超过 `TITLE_MAX=80` / `DESC_MAX=300` 个字符 → `PanwebError(2, "invalid_argument")`；
  - 通过后返回 `strip()` 后的文本。
- `core_publish` / `core_pages` / `core_run` 增加 `title=None, desc=None`，透传到 `_publish_port`；后者在**启动任何子进程前**校验并写入 `entry`（非空才写）。
- `core_set_pin` 复制旧条目字段时把 `title` 一并带上，避免改 PIN 丢标题。
- 控制台发布接口 `/api/publish`、`/api/pages`、`/api/run` 增加 `title/desc` 并直传 core；`/api/share` 改用 `normalize_desc`，去掉自带的截断/替换逻辑。

### 2 分享页渲染（只读 entry，不做业务判断）

- `build_share_page` 用 `models.entry_title(entry)` 作为 `<title>`、`og:title`、页面 `h1`、图标首字母来源。
- 标题、说明继续统一走 `html.escape`；`DESC_ATTR` 仍压成单行并截 160（meta 描述）。
- 未设置 `title/desc` 时输出与现在一致：`h1` 是 `name`，说明走原有默认文案。
- 口令只以布尔 `pin` 传入；`token` 仅用于登录表单 action，不含口令本身。分享页只显示「口令保护」chip。

### 3 CLI 参数与二维码

- `publish/pages/run` 各加 `--title`（≤80）、`--desc`（≤300）、`--qr`。
- `--qr` 在人类可读回执里把分享页 URL（无分享页则公网 URL）渲染成终端二维码；JSON 模式不输出二维码，避免污染机器可读输出。
- 新增 `src/panweb/qr.py`（仅标准库，≤500 行）：字节模式、纠错等级 M、版本 1–10、8 种掩码按罚分择优；`render_terminal(text)` 输出带 4 模块静区、每两行折成一个字符的块码。
- 二维码内容只含 URL，绝不包含 PIN；URL 过长（版本 10 容量外）时回执提示「链接过长，未生成二维码」并照常打印链接。

### 4 控制台

- 发布弹窗在「应用名称」下方增加「分享页标题（可选，≤80）」与「分享页说明（可选，≤300）」，`publish.js` 打开时清空、提交时随 `port/folder/name/pin/expires/share` 一起发给三个发布接口。
- 卡片（`core.js`）与详情抽屉（`apps.js`）优先显示 `title || name`。
- 详情里的分享说明输入上限从 120 调到 300，保存仍走 `/api/share`。
- 二维码继续复用已有 `ui/vendor/qrcode.js`，不新增 vendor，`THIRD_PARTY_NOTICES` 不变。

## 验收

- 新增 `tests/test_share_v2.py`（≤320 行），覆盖：
  1. `normalize_title/desc` 正常值、超长、含换行/控制字符；
  2. CLI 三个命令的 `--title/--desc/--qr` 解析，core 透传并落库到 `entry`；
  3. 分享页渲染 title（回退 name）与 desc、注入 `<script>` 被转义；
  4. 无 title/desc 时分享页仍是 `name` + 默认说明（默认外观不变）；
  5. 设 PIN 时 HTML 只含「口令保护」，不含口令明文；
  6. `qr.encode` 尺寸/矩阵指纹与本地 vendored qrcode.js 一致，`render_terminal` 行数正确，QR 输入不含 PIN。
- 全量基线 260 项必须全绿；`python3 tools/build_ui.py --check`；CI ruff 规则通过。
- 用临时状态目录真实发布一次，浏览器打开分享页，桌面 1440×900 / 移动 390×844 截图存 `docs/screenshots/share-v2/`。

## 文件与规模

- 后端：`models.py`（+8）、`publish.py`（+25，仍 ≤500）、`cli.py`（+9）、`cli_commands.py`（+20）、`ui_actions.py`（+15）、`share.py`（+6）、新增 `qr.py`。
- 前端：`overlays.html`（+12）、`publish.js`（+22，仍 ≤400）、`core.js`（+2）、`apps.js`（+3）。
- `proxy.py` 保持 401 行，不改。

## 明确不做

- 不动 `store.py` 事件流与 `mcp_server.py`；不引入 F2 浏览器/公网分享能力，不做 F3。
- 不新增 npm/CDN 依赖，不生成 PNG 二维码（终端块码已满足「终端可直接扫」且最省依赖）。
- 不改口令校验流程、不放宽代理边界。

# 工作台可用性第二轮（右栏断层 / 分层 / 可发现性 / 左栏 / 空态无障碍）

## 目标

控制台三栏工作台做一次可用性修复，不换皮。重点是第 1、2 条：

1. 右栏对已停止/已到期条目不显示空态，改用「上次发布快照」展示完整信息，并提供「用同样配置重新发布」；停止、改口令、重发、自检不再要求用户回中栏打字。
2. 右栏按分组折叠（链接/状态默认展开，历史/进程默认收起，最近访客放状态区内默认收起），操作区吸底，全部展开状态以布尔持久化。
3. 中栏快捷短语（填模板不执行）、输入时复用 `/api/command` 的解析提示、`↑` 回填仅内存且不含口令明文。
4. 左栏列表按状态过滤并记忆；时间线独立可折叠，未选中时显示全局最近 10 条；排序稳定；搜索空结果有明确提示。
5. 零条目三步引导 + 扫描本机端口；`Cmd/Ctrl+K` 聚焦中栏、`Esc` 关闭抽屉/弹层；复制用 `aria-live` 播报；折叠与快捷短语有可访问名称。

## 关键事实（已核实）

- `core_stop`（`src/panweb/entries.py:143`）与 `sweep_expired`（`src/panweb/lifecycle.py:27`）会把条目从 `state.json` 删除，并删除 `visits/*.jsonl`。因此「停止后仍能展示上次发布信息」必须有一个只读快照，且访问量要在 `stop_entry` 之前取。
- 发布选项优先级已存在：`publish_options.resolve_options`（显式参数 > `.panweb.json` > `publish_defaults` 记忆 > 内置）。重发不得在 UI 复制该逻辑。
- 事件流 `events.log_event` 白名单只含 `url_before/url_after/expires_at/reason/source/port/kind/name`，不含口令；`/api/history?id=` 在 state 中找不到条目时只返回 events。
- 现有 `/api/visits`、`/api/discover`、`/api/detect`、`/api/command` 可直接复用。
- 前端单文件上限 400 行（`tests/test_build.py`），`ui/src/manifest.json` 决定拼接顺序。

## 设计

### 1. 上次发布快照（后端）

新增 `src/panweb/last_deploy.py`：

- `SNAPSHOT_KEY = "last_deployments"`、`MAX_SNAPSHOTS = 5`，写入 `runtime.META_FILE`。
- `snapshot_entry(entry, reason, now=None, domain=None, visits=None)` → 纯函数，返回：
  `id,name,title,kind,port,folder,url,share_url,pinned(bool),expires_at,started,stopped_at,stop_reason,pv{total,uv,last}|None`。
  不写入 `pin`、`share_token` 或任何密钥；`share_url` 由 `entry_share_url` 生成。
- `remember_last(entry, reason="user", visits=None, domain=None)`：按「目标签名」`kind:port` / `kind:folder` 去重，新的在前，最多 5 条。
- `load_snapshots(active_entries=None)`：过滤掉与仍在运行条目同签名的快照（重发成功后列表不出现重复条目）。
- `find_snapshot(entry_id)`。

接线：

- `entries.core_stop`：在 `stop_entry(e)` **之前**取 `aggregate_visits(id)` 与 `load_domain()`，调用 `remember_last(..., reason="user")`。
- `lifecycle.sweep_expired`：reason 为 `"expired"` / `"invalid_expires_at"`；`prune_dead_entries`：`"cleanup"`。
- `ui_actions.handle_get /api/state`：追加 `"last_deployments": last_deploy.load_snapshots(apps)`。
- `ui_actions.handle_get /api/history`：state 找不到条目时回退到 `find_snapshot(entry_id)`，仍用 `deployment.build_detail`，并附加 `from_snapshot: True`、`stopped_at`、`stop_reason`；快照的 `visits` 取自 `pv`。
  找不到快照时保持原有 `{events}` 响应。

安全边界：快照只进 `/api/state` 与 `/api/history` 的只读字段；口令仍只暴露布尔；无新增写接口。

### 2. 右栏分层与吸底（前端）

`ui/src/index.html` 右栏改为分组结构：

- 标题行（名称 + 状态徽章，名称下方一行「上次发布/当前」说明）。
- `dep-group-links`（默认展开）：公网、分享两行 + 二维码（保留放大/下载）。
- `dep-group-status`（默认展开）：口令/有效期/发布时间/PV/UV/最近访问/最近重建/重建次数；已停止快照额外显示「停止时间」「停止原因」。
  - 状态区内嵌 `dep-group-visitors`（默认收起）：「最近访客」列表。
- `dep-group-history`（默认收起）：历史链接（沿用 `detail.links`，标「当前/已失效」）。
- `dep-group-process`（默认收起）：三节点进程可视化（不改动节点与脉冲）。
- 底部 `dep-actions`：`position: sticky; bottom`，吸在详情面板底部；停止保留二次确认（`askStop`）。

分组控件：`<button class="dep-group-btn" aria-expanded aria-controls>` + 内容容器 `hidden`；点击时切换并把状态写入 `localStorage["panweb-dep-groups"]`，值为 `{links:boolean,status:boolean,visitors:boolean,history:boolean,process:boolean}` 的 JSON（只存白名单布尔，非法/缺失回退默认）。快捷键可达（原生 button），可访问名称由按钮文案提供。
新增 `ui/src/js/depgroups.js`（分组与最近访客渲染、`loadVizVisits`）。为避免超 400 行，`viz.js` 不再膨胀。

已停止/已到期视图：

- `renderViz()` 分支：无选择 → 空态（带「扫描本机端口」）；hosted → 既有文案；选中 `STATE.last_deployments` 中的快照 → `renderStopped(snap)`；否则原逻辑。
- `renderStopped` 复用同一套 DOM：链接、二维码、状态、历史链接（`/api/history?id=`，后端回退）、进程区显示「已停止」占位。
- 操作区在快照态：主按钮「用同样配置重新发布」；「改口令」在有输入时等价于「重发并设口令」；「停止/重试通道」禁用并给出 `title` 说明；「重新自检」改为「检查源状态」——端口用 `/api/discover` 判断源端口是否还在监听，文件夹用 `/api/detect` 判断类型，结果用既有气泡反馈，不装作隧道自检。
- 重发（`vizRepublish`）：`POST /api/publish {port: snap.port, name: snap.name, title?, pin?}` 或 `POST /api/pages {folder: snap.folder, name?, pin?}`，`async: true`；**不传 expires/share**，由 `resolve_options` 使用既有记忆；复用 `pollJob`，成功后 `onJobSuccess` 自动选中新 id，右栏立即切到新条目。快照缺 `port`/`folder` 时直接报「上次目标缺失」，不猜。
- `lastpub.js` 承载快照渲染/重发/源检查；`viz.js` 保留活动条目详情、二维码、节点。

### 3. 中栏可发现性

- `partials/pages.html`：快捷短语改为「发布端口 / 发布文件夹 / 停止当前 / 检查一下」，调用 `fillTemplate("发布 <端口>", "<端口>")` 等；占位片段被选中，直接输入即替换；点击只填不执行。每个 chip 有 `aria-label` 与可聚焦。
- 新增 `ui/src/js/composer.js`：
  - `fillTemplate(text, token)`。
  - 输入后 400ms 防抖调用 `POST /api/command`；失败时把 `error.hint` 显示在 `#cmd-hint-line`（同时保留 `examples` 的可点示例）；成功显示「语法可执行」；空输入清空。前端不复制语法规则，只用后端返回。
  - `↑/↓` 在内存数组 `CMD_HISTORY` 中回填；入栈前用 `stripPin(text)` 去掉 `pin=xxx` / `pin xxx`，绝不写 localStorage；数组上限 30。
- `commands.js`：提交时把 `stripPin(text)` 推入历史（若 `stripPin` 存在）。

### 4. 左栏列表 / 时间线

- 状态过滤 chips：全部（默认）、运行中、已停止、已到期、云端托管；`localStorage["panweb-asset-filter"]` 记忆，非法值回退 `all`。
- 列表数据源 = `STATE.apps` + `STATE.last_deployments` + `STATE.hosted`；状态映射：`online/offline/expired/hosted`；快照按 `stop_reason` 归入 `expired` 或 `offline`。
- 排序稳定：运行中条目按 `started` 倒序，快照按 `stopped_at` 倒序，托管条目按名称；同分按 id 保证稳定。
- 搜索无结果：文案「没有匹配…（当前筛选：X）」+「清除筛选」按钮。
- 时间线：标题行加折叠按钮（`aria-expanded`，`localStorage["panweb-rail-timeline"]` 布尔）；未选中条目时拉取 `/api/history?limit=10` 展示全局最近变更，而不是空块；选中条目仍按 id 读取（既有缓存）。刷新按钮保留。
- 空态（零条目）：左栏显示三步摘要 + 「扫描本机端口」。

### 5. 空态引导 + 无障碍

- 中栏 `#guide-card`（`assets.length === 0` 时显示，三步：选择要发布的东西 → 确认能被访问 → 发送给别人；按钮：发布端口 / 发布文件夹 / 扫描本机端口）。右栏空态同样给「扫描本机端口」。
- `scanPorts()` 调 `/api/discover`；结果渲染端口/标题/进程，点击填入 `发布 3000` 或直接打开「高级发布-端口」。
- `Cmd/Ctrl+K`：在 `apps` 页聚焦 `#cmd-input`（阻止浏览器默认）；其他页保留既有命令面板。`Esc`：关闭右栏/左栏抽屉，并关闭当前可见的 `.overlay.show`（含二维码、发布、停止确认、⌘K）。
- 复制：`apps.js` 的 `copyText` 成功后调用 `announce("已复制…")`，写入 `#sr-live`（`aria-live="polite"`），视觉 toast 不变；失败也播报。
- 折叠按钮、快捷短语、过滤 chips 均使用原生 `button` + `aria-pressed`/`aria-expanded`。

## 约束与红线

- 不改 `publish.py`、`cli_commands.py`、`share.py`。
- 无框架 / npm / CDN；只改 `ui/src` 后 `python3 tools/build_ui.py`，`--check` 必须通过。
- 口令明文不得进 DOM 属性、localStorage、对话持久化；`↑` 历史与提示请求都不得保存/回显口令（历史先剥离 pin）。
- 只消费现有 API（`/api/state`、`/api/history`、`/api/visits`、`/api/command`、`/api/discover`、`/api/detect`、`/api/publish`、`/api/pages`、`/api/stop`、`/api/pin`、`/api/check`、`/api/recover`）；不新增高频轮询（右栏访客只在选择变化时取一次）。
- 全量测试 399 → 新增约 14，全部绿灯；`ruff check --select E9,F63,F7,F82 src tools tests` 通过。
- 每个 `ui/src/js/*.js`、`styles/*.css` ≤ 400 行。
- Git 只 add 具体文件，不 push、不打 tag、不回滚他人提交。

## 验收

自动化：

- `python3 -m unittest discover -s tests`：基线 399 + 新增全绿。
- `ruff check --select E9,F63,F7,F82 src tools tests`。
- `python3 tools/build_ui.py --check`。

真机（临时 `PANWEB_HOME`，验完 stop 全部并清理隧道）：

- 1440×900：详情首屏（名称/状态、两条链接、二维码、关键状态、吸底操作区）；折叠展开态（历史+进程打开）；已停止条目详情与「用同样配置重新发布」；零条目三步引导。
- 390×844：详情抽屉（底部操作条）；零条目空态。
- 实操：停止后右栏重发成功且选中新条目；折叠状态刷新后保持；`↑` 回填有效且 localStorage 无口令；`Cmd+K`/`Esc` 生效；复制有 `aria-live` 播报。

## 风险与已知取舍

- 快照存于 `meta.json`，只保留 5 条、停止时覆盖同目标；旧记录不会自动过期（提供「清除」入口须另开需求）。
- 重发使用快照的 port/folder/name，有效期/分享取后端记忆；若用户最近改过记忆，结果可能与上次不完全相同（这是既有语义，不在 UI 猜）。
- 已停止条目的「停止/自检」无对象，改为禁用+说明；「检查源状态」明确标注检查的是源而非隧道。
- 全局时间线最多 10 条，由 `/api/history?limit=10` 从日志尾部反向读取，开销与现有抽屉一致。
- `/api/command` 输入时联调会把当前输入（含临时口令）发到本机后端解析，但不会落盘、不返回给提示渲染；提交前仍只在内存。

## 需批准

以上方案涉及新增后端模块 `last_deploy.py`、`entries.py`/`lifecycle.py`/`ui_actions.py` 接线，以及 `ui/src` 的结构调整。批准后按 `tasks.md` 执行。

# F3 发布历史与变更时间线 规格

结论：新增一条纯旁路的 append-only 事件流（`~/.panweb/events/YYYYMMDD.jsonl`），只在既有状态变更处加埋点；不改 `state.json` 结构，不做 F1 的分享模板改动。

## 一、数据与写入

### 文件布局
- `runtime.EVENTS_DIR = ~/.panweb/events`，`set_home()` 同步更新。
- 按天分文件：`events/20261104.jsonl`，单文件只追加、不改写。
- 每条一行 JSON：`{"ts": float, "entry_id": str, "type": str, "summary": str, "details": {...}}`。
- 不轮转删除；单条约 200B，日文件按天自然分裂（保留策略留后续）。

### `src/panweb/events.py`（新增，标准库）
- `EVENT_TYPES = {"publish", "restart", "url_change", "pin_change", "expire", "stop", "error"}`。
- `SAFE_DETAIL_KEYS = {"url_before", "url_after", "expires_at", "reason", "source", "port", "kind", "name"}`。
- `log_event(entry_id, type, summary, **details) -> bool`：
  1. 未知 type / 空 entry_id → 丢弃并返回 False（旁路不抛错）；
  2. `summary` 去掉控制字符、去空白、截 160；
  3. `details` 只保留白名单键；值只接受 str/int/float/bool/None；字符串去掉控制字符、截 300；
  4. `url_before/url_after` 只留 scheme+host+path，去掉 query/fragment/userinfo；
  5. `os.makedirs(EVENTS_DIR, mode 0o700)` 后用 `json_lock(day_file)` 追加；
  6. 任一步失败 → `log_activity("system", "事件日志写入失败：<原因>")` 并返回 False，**绝不向上抛**。
- 隐私：口令/PIN 没有白名单键；`pin`、`token`、`authorization`、`password`、`secret` 等传入即被丢弃；调用方只传公开 URL、时间、来源、原因。
- `read_events(entry_id=None, limit=30) -> list[dict]`：
  - `limit` 夹在 1..200；
  - 从最新日文件开始，逐文件**从文件尾按 8KB 块反向读**，凑够 limit 条（或按 entry 过滤后凑够）即停；
  - 返回按时间倒序（最新在前）；跳过坏行。

## 二、埋点位置（只加调用，不改结构）

| 位置 | 事件 | details |
|---|---|---|
| `publish._publish_port` 成功返回前（仅 register=True） | `publish` | `url_after`、`expires_at`、`source="publish"` |
| `publish._publish_port` 的 `except BaseException` | `error` | `reason=异常类名`、`source="publish"` |
| `publish.core_set_pin` 两个分支 | `pin_change` | `url_before/url_after`、`source=actor` |
| `supervisor._restart_entry_tunnel` 成功写 state 后 | `url_change`（URL 变了）/ `restart`（未变） | `url_before/url_after`、`reason`（health/manual/startup） |
| `supervisor.restart_entry_proxy` 成功 | `restart` | `url_after`、`reason="proxy"`、`source="system"` |
| `supervisor.recover_failing` 失败分支 | `error` | `reason=异常类名`、`source="system"` |
| `entries.core_stop` 每个命中条目 | `stop` | `url_before`、`source`（cli/ui）、`reason="user"` |
| `lifecycle.sweep_expired` | `expire` | `url_before`、`expires_at`、`source="system"` |
| `lifecycle.prune_dead_entries` | `stop` | `reason="cleanup"`、`source="system"` |

- `_restart_entry_tunnel` 增加可选 `reason="auto"`，`recover_failing` 传 `"manual"`、`recover_all` 传 `"startup"`、健康巡检传 `"health"`；`restart_entry_tunnel` 透传。
- `core_stop(target, source="ui")`；CLI `cmd_stop` 传 `source="cli"`。
- `events.log_event` 在 `publish.py` 中只以调用形式出现，不搬函数。

## 三、读取

### CLI
`panweb history [id] --json --limit N`：
- `--limit` 默认 30，夹 1..200；
- JSON：`{"ok": true, "data": {"events": [...], "limit": N, "id": id|null}}`；
- 人读：每行 `YYYY-MM-DD HH:MM:SS  类型  摘要`，有 URL 变化时追加 `旧网址 → 新网址`；
- 空态：`还没有变更记录。发布、改口令、重建通道或停止后，这里会出现时间线。`

### API
`GET /api/history?id=<entry_id>&limit=<n>`：
- 返回 `{"ok": true, "data": {"events": [...]}}`；
- `id` 可选，非法 limit 回退 30，上限 200；
- 必须走 `read_events` 的 tail 实现，禁止整文件读取（不复用 `/api/log` 的 `f.read()` 写法）。

### UI
- 详情抽屉新增「时间线」区块（`ui/src/partials/overlays.html`），列表复用 `.visit-list/.v-row/.v-time/.v-kind`：
  - 每行：本地时间、类型中文标签、摘要；`url_before/url_after` 存在时显示旧值 → 新值；
  - 空态：`还没有变更记录；发布、改口令、重建通道或停止后会出现在这里。`
- `apps.js` 的 `openDrawer` 调一次 `loadTimeline(id)`；不跟 2.5 秒的 `loadDetail` 轮询重复请求。
- 不新增框架、不新增文件；`apps.js` 保持 ≤400 行。

## 四、测试

新增 `tests/test_history.py`（≤320 行）：
1. 写入/读取：字段齐全、倒序、按 entry 过滤、limit 截断；
2. 敏感信息负向：传 `pin/token/authorization/password/secret` 与未知键，原始文件不含这些键和值；URL query/fragment 被剥离；
3. 写入失败旁路：patch 追加函数抛 `OSError`，`log_event` 返回 False 且 activity 出现告警，不抛异常；
4. tail：造 >5MB 日文件，统计 `read()` 字节数 < 文件大小，仍能取到最新 N 条；
5. CLI `history --json` 与人读输出；
6. API `/api/history` 过滤、limit 上限、未知 entry 返回空列表；
7. 埋点集成：`core_stop(source="cli")` 落 `stop` 事件；`sweep_expired` 落 `expire` 事件；
8. 默认旁路：事件写入失败不影响 `core_stop` 的返回结果。

## 五、验证与提交

- 全量基线 260 项全绿；`python3 tools/build_ui.py --check`；CI ruff。
- 临时 `PANWEB_HOME` 真实跑 发布 → 改 PIN → stop，`panweb history <id>` 能看到 `publish → pin_change → stop`；控制台抽屉截图存 `docs/screenshots/history/`（桌面）。
- 提交（不 push）：①事件存储与测试；②埋点；③CLI history；④API 与 UI 时间线；⑤截图与规格若未随首提交。

## 六、明确不做

- 不改 `state.json`、不改 `activity.json` 老结构。
- 不做事件压缩/归档清理、不做事件回放或状态重建。
- 不碰 `share.py` / 分享页渲染（F1 后续再改）。
- 不把 PIN、share token、Authorization 等任何凭据写入事件或日志。

# state v2：根治 entry.target 多态

## 1. 目标与范围

删除发布条目里的联合字段 `target`（历史上可能是 `int` 端口或 `str` 文件夹），
以 `kind` 作为判别式，端口/运行类条目只写 `port: int`，静态文件夹条目只写
`folder: str`。`state.json` 顶层写入 `schema_version: 2`。

不做：`share.py` 页面渲染、安全边界、依赖、MCP 工具参数名（`stop`/`check_app`
的 `target` 是用户输入参数，不是 state 字段）。

## 2. 最终数据结构

`state.json`（v2）：

```json
{
  "schema_version": 2,
  "entries": [
    {"id": "a1", "kind": "port", "port": 3000, "...": "..."},
    {"id": "b2", "kind": "pages", "folder": "/Users/x/site", "...": "..."}
  ]
}
```

- v1 兼容格式：顶层直接是 `entries` 数组。
- `schema_version` 语义：文件格式版本；`2` 表示条目用 `port`/`folder` 判别字段。
  未知值或缺失按 v1 读入并迁移。
- 未知顶层字段、未知条目字段：读取时原样带到内存，`save_state` 写回时保留
  （不清理用户/第三方数据）。
- 迁移只发生在**读**：`load_state()` 内调用 `migrate_entries()`；`save_state()`
  只写 v2。旧文件在首次被旧格式读取/覆盖前，尽力备份到
  `state.json.v1-backup`（已存在则不覆盖，失败不阻断）。

## 3. 迁移规则（幂等）

`store.migrate_entries(entries)` 为纯函数，逐条：

| kind | 旧 target | 新字段 |
| --- | --- | --- |
| `pages` | 任意字符串 | `folder = target`（已有 `folder` 时不覆盖） |
| 其他（默认端口） | 可转 int 且在 1..65535 | `port = int(target)`（已有 `port` 时不覆盖） |
| 其他 | 非数字字符串 | 归入 `folder`（只可能是历史 run 条目） |
| 任意 | `target` 不可用/布尔/空 | 丢弃该字段，不写新字段 |

迁移后必定删除 `target`；输入条目中除 `target` 外的键全部保留。
幂等定义：`migrate_entries(migrate_entries(x)) == migrate_entries(x)`，
且对同一份磁盘旧 state 连续两次 `load_state()` 得到相同结果。

## 4. 访问器（models.py）

| 访问器 | 语义 |
| --- | --- |
| `entry_port(entry)` | 仅 `kind == "port"`；把 `port` 转 int，1..65535 之外或缺失返回 `None` |
| `entry_folder(entry)` | 仅 `kind == "pages"`；返回非空 `folder` 字符串，否则 `None` |
| `entry_local_port(entry)` | 隧道回源端口：`proxy_port or local_port or entry_port(entry)`；不再读 `target` |

被替换的调用点：

- `entries.entry_alive`：`entry_port` + 代理端口检查。
- `entries.entry_nodes` 的 source 节点：`entry_folder` / `entry_port`。
- `supervisor.restart_entry_proxy`：`entry_folder` / `entry_port`。
- `supervisor._source_ready`：`entry_folder` / `entry_port`。
- `supervisor._restart_entry_tunnel`、`domain.*`：继续用 `entry_local_port`
  （实现内已去掉 `target`）。
- `healthcheck.host_evidence`：`entry_port`。
- `publish._publish_port` 写入口：`kind=port` 写 `port`，`serve_dir` 时写
  `kind=pages` + `folder`。
- `publish.core_set_pin`：`entry_port(entry)` 取代 `entry.get("target")`。
- `cli_render.source_text`：按 `kind` 分发到 `entry_folder` / `entry_port`。
- `discovery.core_discover`：端口条目用 `entry_port`。
- `folders.quick_picks`：`entry_folder`。
- `proxy._app_online`：`entry_folder` / `entry_port`。
- `ui_actions._run_or_job`：single-flight key 只取 `port`/`folder`。
- `visits`：按 id 聚合，不读源字段，无需改动（回归确认）。

## 5. doctor 检查

`discovery.core_doctor(force=True)` 新增：

```json
"legacy_target": {
  "ok": false,
  "count": 2,
  "ids": ["a1", "b2"],
  "message": "检测到 2 条旧版 target 字段；读取时会自动迁移为 port/folder",
  "hint": "无需手工处理；下次写入后 state.json 即为 schema_version 2"
}
```

`panweb doctor` 文本输出新增一行：有遗留时 `⚠️` + 条数，无遗留时
`✅ state v2（无遗留 target 字段）`。第三方脚本可读 JSON 的
`legacy_target` 自查。检查基于**原始磁盘 JSON**，不受 `load_state` 迁移影响。

## 6. 前端对齐

`ui/src/js/apps.js`、`core.js`、`workbench.js` 中读取 `a.target` 的卡片/详情/
搜索逻辑改为 `a.port` / `a.folder`，保持 kind 分支；改完
`python3 tools/build_ui.py` 重建 `ui/index.html`，`--check` 必须通过。

## 7. 验收

- `env -u PYTHONHOME python3 -m unittest discover -s tests`：365 项基线全绿，
  新增迁移/访问器/doctor/前端字段用例。
- `env -u PYTHONHOME python3 tools/build_ui.py --check` 通过。
- `uvx ruff check --select E9,F63,F7,F82 src tools tests` 通过。
- 单文件 Python < 500 行；`publish.py` < 400。
- 提交按主题拆分：迁移与访问器 / 读路径切换 / 写路径与 doctor / 前端与测试。
  只 `git add` 具体文件，不 push、不推 tag。

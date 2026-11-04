# F2 Agent 一键发布闭环 规格

结论：把 MCP 发布类工具从「同步阻塞」改成「提交即返回 job → 轮询 get_job」，补齐可被 Agent 发现的参数 schema，并新增项目根 `.panweb.json` 作为发布默认值的项目级来源；回执统一为同一形状。前置约束：`publish.py`（499 行）与 `cli_commands.py`（500 行）已到单文件上限，先按主题拆分、只移动不改语义，再实现新功能。

## 1 模块拆分（先做，语义不变）

| 新模块 | 从 `publish.py` 移出 | 说明 |
|---|---|---|
| `publish_defaults.py` | `DEFAULTS_KEY`、`load_publish_defaults`、`remember_publish` | `meta.json` 的上次发布记忆 |
| `publish_text.py` | `TITLE_MAX`、`DESC_MAX`、`_normalize_text`、`normalize_title`、`normalize_desc` | 标题/说明校验 |
| `project.py` | `core_detect` | 项目类型识别 |
| `publish_support.py` | `NODE_DEV_PORTS`、`PORT_HINT_RE`、`_emit`、`_pick_port`、`_ensure_publishable_port`、`_sniff_port`、`is_risky_port` | 发布前的探测/挑选/端口守卫 |
| `publish_options.py` | 新增 | 配置 + 记忆 + 显式参数的优先级解析 |

`publish.py` 保留 `_spawn_proxy`、`_publish_port`、`core_publish`、`core_set_pin`、`core_run`、`core_pages`，并从新模块 **re-export** 原有名字（`load_publish_defaults`、`remember_publish`、`normalize_title/desc`、`core_detect`、`_pick_port`、`_sniff_port`、`_ensure_publishable_port`、`is_risky_port`、`_emit`）。这样 `panweb.publish.*` 的既有导入与 `mock.patch.object(publish, ...)` 目标全部保持不变；拆分后 `publish.py` < 400 行。

`cli_commands.py` 抽出一个渲染模块 `cli_render.py`（`CHECK_ICONS`、`_source_text`、`render_check`、`_report_check`、`_entry_for_json`、`_print_share_qr`），`cli_commands` re-export `_source_text`（测试直接引用）。命令函数留在 `cli_commands.py`，因为测试会 patch `cli_commands.core_run` / `load_publish_defaults` / `core_list`。拆分后 `cli_commands.py` < 450 行。

## 2 `.panweb.json` 项目配置

- 位置：发布文件夹（`pages` / `run`）或 `publish` 的项目目录（CLI 取 `cwd`，MCP 取 `folder` 参数，缺省 `cwd` / `.`）。**只读本目录，不向上递归**；不存在即无配置。
- 字段与校验：

| 字段 | 类型 | 规则 |
|---|---|---|
| `port` | int | 1–65535，布尔值不算 int；仅 `publish` 生效 |
| `script` | string | 去空白非空、无控制字符、≤100；仅 `run` 生效 |
| `name` | string | 去空白、无控制字符、≤120 |
| `expires` | string | `1h` / `1d` / `7d` / `permanent` |
| `share` | bool | 严格布尔 |
| `title` | string | 沿用 `TITLE_MAX=80`、无控制字符 |
| `desc` | string | 沿用 `DESC_MAX=300`、无控制字符 |
| `pin_policy` | string | `none` / `required`；`required` 且未提供口令 → `pin_required` |

- **未知键一律拒绝**（含 `pin`、`token`、`password`），错误类型 `invalid_config`，hint 列出支持字段。因此 PIN 明文没有合法落盘位置。
- 顶部不是 JSON 对象、类型错误、枚举越界、超长/控制字符 → `invalid_config`，message 指出字段，hint 指出修法。
- 权限：文件 mode 对 group/other 可读（`mode & 0o044`）时产生 `config_permission` 告警（不阻断发布）；`panweb doctor` 的 `data.project_config` 同时给出告警或解析错误。
- 敏感性：配置文件内容不得进入事件流、活动日志、分享页或 MCP 回执。发布只消费校验后的字段；告警只包含路径与权限位，不回显文件内容。

### 优先级

显式参数 > `.panweb.json` > 上次发布记忆（`meta.json`）> 内置默认值。冲突可被测试断言。

| 字段 | 显式参数 | 配置 | 记忆 | 内置 |
|---|---|---|---|---|
| `port` | CLI/MCP `port` | `port` | `last_port`（仅 `_pick_port`） | 自动探测 |
| `script` | MCP `script` | `script` | — | `dev` / `start` |
| `name` | `name` | `name` | — | `port-<端口>` / 文件夹名 |
| `expires` | `expires` / `permanent=""` | `expires` | `expires` | `""`（永久） |
| `share` | `share` | `share` | `share` | `true` |
| `title` / `desc` | `title` / `desc` | 同名字段 | — | `None` |
| `pin` | `pin` | 不允许（只有 `pin_policy`） | — | `None` |

`share` 缺省解析为 `true`，与现有 CLI / 控制台一致；MCP 显式传 `false` 仍然直连。`pin_policy=none` 不禁止显式口令。

## 3 MCP 工具与 schema

| 工具 | 作用 | 关键参数 |
|---|---|---|
| `discover_apps` | 扫描本机候选 | — |
| `publish_port` | 异步发布端口 | `port`、`folder`、`name`、`pin`、`expires`、`share`、`title`、`desc`、`wait` |
| `publish_pages` | 异步发布静态文件夹 | `folder`、`name`、`pin`、`expires`、`title`、`desc`、`wait` |
| `run_project` | 异步启动并发布项目 | `folder`、`script`、`name`、`pin`、`expires`、`share`、`title`、`desc`、`wait` |
| `get_job` | 查询/等待 job | `id`、`wait` |
| `stop` / `list_apps` / `status` / `check_app` / `set_compat` | 原能力 | 原有参数，补齐 description |

- 所有 schema 为 `type: object`；`port` integer（1–65535）；`expires` enum `["1h","1d","7d","permanent"]`；`share` boolean；`title` `maxLength: 80`；`desc` `maxLength: 300`；`wait` boolean 默认 `false`；`pin` 描述明确「仅本次会话内存 / stdin，不落盘」。
- `folder` 缺省 `"."`；`publish_port` 的 `folder` 只用于定位 `.panweb.json`。
- 发布类工具提交后立即返回 job id 与 `state="running"`；同一目标重复提交复用 `jobs.start` 的 single-flight（key 为端口或绝对文件夹路径），不另起队列。
- `wait=true`：最多等待 `WAIT_TIMEOUT=20` 秒；完成则返回最终回执；超时返回 `ok=true, state="running", job_id`（**不算失败**），hint 提示用 `get_job` 继续轮询。
- job 保留策略沿用 `jobs.py`（单进程、最多 20、只淘汰终态）；MCP 不修改全局语义。

## 4 统一回执

成功、进行中、失败都是同一形状：

```json
{
  "ok": true,
  "job_id": "ab12cd34",
  "state": "running|succeeded|failed",
  "id": null,
  "url": null,
  "share_url": null,
  "expires_at": null,
  "check": null,
  "error": null,
  "steps": ["准备中…"],
  "step": "准备中…"
}
```

- 失败：`ok=false`，`error={"type","message","hint"}`；`state="failed"`。
- 未知 job：`error.type="job_not_found"`，hint 提示重新提交或控制台重启会丢 job。
- 未知工具：`error.type="unknown_tool"`，MCP 响应 `isError=true` 但正文仍是回执形状。
- `check` 只放已落地的自检结论（`entry["check"]`）；后台自检未完成时为 `null`，不阻塞 job。

## 5 错误码

| `error.type` | 触发 |
|---|---|
| `invalid_argument` | 端口/类型/参数非法 |
| `invalid_config` | `.panweb.json` 未知键、类型、枚举、JSON 语法 |
| `pin_required` | `pin_policy=required` 但未提供口令 |
| `job_not_found` | get_job 的 id 不存在或已淘汰 |
| `unknown_tool` | tools/call 的工具名不存在 |
| `internal_error` | 非 PanwebError 异常（message 保留，hint 建议重试 / 看日志） |
| 其余 | 沿用 `PanwebError.err_type`（`port_not_serving`、`tunnel_failed`、`unsafe_folder` 等） |

## 6 测试清单

- `tests/test_mcp.py`：schema 契约（每个发布工具的 `port/folder/script/pin/expires/share/title/desc/wait` 按工具可发现、类型与 enum 正确）；异步提交→轮询→成功；`wait` 超时不算失败；失败路径经 `get_job` 拿结构化错误；重复提交复用 job；未知 job；回执字段齐全且不含 PIN。
- `tests/test_project_config.py`：字段校验、未知键/`pin` 拒绝、权限告警、不向上递归、优先级逐字段断言、`pin_policy=required`、配置内容不进入事件流/MCP 回执。
- `tests/test_f2_split.py`：`publish.py` < 400、`cli_commands.py` < 450；`core_*` 签名保留；`panweb.publish` 仍可导入/ patch 旧名字。
- 全量基线 332 项全绿；`python3 tools/build_ui.py --check`；`ruff check --select E9,F63,F7,F82 src tools tests`。
- 真实 stdio MCP 会话：发布临时静态目录 → 拿 job → 轮询成功 → 收 URL/回执；对不存在文件夹提交 → `get_job` 拿结构化错误；回执 JSON 存 `docs/evidence/f2-agent/`。

## 明确不做

- 不改 `ui/src` 与 `ui/index.html`（回执无需控制台展示）。
- 不动 `share.py` 页面渲染、口令校验、代理边界、事件流脱敏规则。
- 不新增第三方依赖；不引入跨进程队列；不做 job 历史持久化。
- 不把 PIN 放进 `.panweb.json`、日志、事件流或 MCP 回执。

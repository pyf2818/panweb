# P0 加固规格（12 条）

结论：12 条在现行代码中均未修复；按“代理语义、状态机、类型崩溃、安全与部署”四组落地，每条先补会变红的回归测试。

## 调研结论（现状校正）

| # | 位置（按函数/模块定位） | 现状 |
|---|---|---|
| 1 | `proxy.py` 的 `do_GET = ... = _handle` | 未注册 `do_OPTIONS`，落到 `BaseHTTPRequestHandler` 默认 501 |
| 2 | `proxy.py` 的 `_handle` / `_forward` 传 `client_address[0]`；`upstream.forward_headers` | 客户端 IP 恒为 127.0.0.1；入站 `X-Forwarded-For`/`X-Real-IP` 原样保留后再追加，产生重复头；`DROP_HEADERS` 未含这些头 |
| 3 | `proxy.py` 的 `_forward` 只读 `Content-Length` | `Transfer-Encoding: chunked` 被当空 body；不支持的编码静默置空 |
| 4 | `proxy.py` 的 `_forward` except 分支 | 无 `headers_sent` 记录；响应已开始后仍尝试 `_text_error(502)`，可能拼出第二个状态行 |
| 5 | `supervisor.health_loop` | `status == 0` 才累计；502/530 直接落到 `restart_entry_tunnel`，立即换 URL |
| 6 | `ui_actions._recover` | 遍历全部条目无条件 `restart_entry_tunnel`，同步阻塞；未复用 `jobs.py` |
| 7 | `publish.core_set_pin`、`pins.write_pin` | 改 PIN 只写文件，`state["pinned"]` 不更新；直连条目改 PIN 会新建 id，visits/secrets 随旧 id 孤立 |
| 8 | `cli_commands.cmd_run`（`%d` 格式化 `entry["target"]`）、`cmd_publish` | 静态文件夹走 `core_pages` 返回 `kind=pages,target=str`，`cmd_run` 成功回执触发 TypeError |
| 9 | `hosting.core_host` | 构建/复制后未写 `.nojekyll`，Jekyll 丢弃 `_next`/`_astro` |
| 10 | `safety.check_pages_folder` | 只做“精确等于”黑名单；`~/.ssh` 等敏感子目录可发 |
| 11 | `entries.stop_entry` + `forwarder.FORWARDERS` | CLI 是独立进程，拿不到控制台内的 Forwarder；`stop` 后转发器仍监听、仍转发 |
| 12 | `store._load_json` / `store.load_state` | JSON 解析失败静默返回 `[]`；无备份、无告警、UI/CLI 无提示 |

## 设计决策

### 1 OPTIONS
- `proxy.py` 新增 `do_OPTIONS`：静态只读发布返回 `204 + Allow: GET, HEAD, OPTIONS`；端口发布把 OPTIONS 转发给上游，由应用自身的 CORS 中间件作答（panweb 不添加 `Access-Control-Allow-Origin`，安全边界不放宽）。
- 口令门禁与过期判断沿用现有入口语义，不新增放行路径。

### 2 客户端 IP 与可伪造头
- `upstream.py` 新增 `client_ip(headers, peer)`：按 `CF-Connecting-IP` → `True-Client-IP` → `X-Real-IP` → `X-Forwarded-For` 首个合法值 → 对端地址的顺序取值；用 `ipaddress.ip_address` 校验，非法值忽略。
- `upstream.forward_headers`：入站 `x-forwarded-for/proto/host`、`x-real-ip`、`forwarded`、`cf-connecting-ip`、`true-client-ip` 一律剥离；配置了上游鉴权时，再剥离 `Authorization` 或同名的自定义鉴权头，最后写 panweb 自己的值。
- 未配置上游鉴权时保留访客自带的 `Authorization`（应用自身登录仍可用）。

### 3 请求体
- 新增 `src/panweb/proxy_body.py`：`read_request_body(headers, rfile, limit)`。
- 支持 `Transfer-Encoding: chunked` 解码（含 trailer、大小上限），解码后按 `Content-Length` 透传；`chunked` 以外的 TE 返回 411；格式非法 400；超限 413；`Content-Length` 非法 400。
- `proxy._forward` 改用该函数；`runtime.MAX_PROXY_BODY` 仍为唯一上限。

### 4 响应已发出
- `ProxyHandler.end_headers` 置 `_response_started=True`；`_handle` / `do_OPTIONS` 入口重置。
- 转发异常时：未开始响应才写 502；已开始响应只设 `close_connection=True` 并关闭连接。

### 5 健康判定
- `HEALTH_FAILS_LIMIT = 3`；把单条巡检逻辑抽成 `supervisor._health_step(entry)` 以便测试。
- 0/502/530 都累计失败；达到阈值后：
  - 隧道进程仍活：仅重启代理（有 `proxy_port` 时），保留 URL；
  - 隧道进程确死：才 `restart_entry_tunnel` 重建 URL；
  - 无代理的直连发布只记活动，不换 URL。

### 6 手动恢复
- `supervisor.recover_failing(progress=None)`：只处理 `not entry_alive(entry)` 或 `pinned_status(url, 6) in (0, 502, 530)` 的条目；返回 `{"checked": n, "recovered": [...]}`。
- `ui_actions` 的 `/api/recover` 一律 `jobs.start("recover", ...)` 并返回 job id；`ui/src/js/workspace.js` 改为轮询 `/api/job`，完成后提示恢复数量。
- 同步入口（启动时 `recover_all`）保持现状，不阻塞 UI。

### 7 改 PIN
- `pins.write_pin`：写/删口令文件后，在 `state_lock()` 内按 id 更新 `state["pinned"]`（条目不存在则无操作）。
- `_publish_port` 增加可选 `entry_id`；`core_set_pin` 对直连条目改 PIN 时复用原 id 建代理+隧道，`replace_entry` 原地替换，再停旧资源。
- `entries.stop_entry` 增加 `clear_secrets=True` 参数；改 PIN 停旧条目时传 `False`，不删 visits/secrets。
- 旧条目字段（app_pid/app_log/launched/risky/host_mode/desc/name/expires_at）继续保留。

### 8 target 多态
- 本次只做兼容层：`cli_commands` 新增 `_source_text(entry)`，按 `kind == "pages"` 显示文件夹，否则用 `entry_local_port(entry)` 显示 `http://127.0.0.1:<port>`；`cmd_publish`/`cmd_run`/`cmd_list` 统一走它。
- 根治（`target` 拆成 `target_port` 与 `source_path`）不在本次范围，写进最终汇报的后续任务。

### 9 .nojekyll
- `hosting.py` 新增 `_ensure_nojekyll(stage)`，在上传/构建两种分支之后、`git init` 之前写入空文件。

### 10 敏感目录
- `runtime.py` 新增 `UNSAFE_PAGE_PREFIXES`：`~/.ssh`、`~/.aws`、`~/.gnupg`、`~/.config`、`~/.panweb`、`~/.kube`、`~/.docker`、`~/Library/Keychains`。
- `check_pages_folder` 用 `realpath` + `commonpath` 做前缀判断（目录本身及其所有子目录都拒绝）；原有精确黑名单保留。

### 11 跨进程停止 Forwarder
- `runtime.py` 新增 `FORWARDERS_DIR`（`~/.panweb/forwarders`，0700），纳入 `ensure_private_dirs`。
- `Forwarder` 支持 Unix 控制 socket：`enable_control(entry_id)` 在 `FORWARDERS_DIR/<id>.sock` 监听，收到 `STOP` 即 `stop()`；`stop()` 关闭 TCP/控制服务并删除 socket。
- `forwarder.stop_remote(entry_id)` 供 CLI/其他进程发送 STOP。
- `entries.stop_entry`：本地 `FORWARDERS` 有实例就本地停；否则调用 `stop_remote`。
- 启动清理删除不属于当前 state 的陈旧 `.sock`。

### 12 状态损坏
- `store.load_state` 单独处理解析失败：把 `state.json` 改名为 `state.json.corrupt-<时间戳>` 留证；模块内记录 `state_issue()`（路径/时间/说明）；`log_activity` 告警；返回 `[]`。
- `/api/state` 增加 `state_issue` 字段；`cmd_list` 在空列表前打印可读提示。
- 文件不存在仍按正常空态返回 `[]`；权限等其他 OSError 只告警不改名。

## 文件与行数约束
- `proxy.py` 现 444 行，新增会接近 500：先把 `_serve_static` 拆到 `src/panweb/proxy_static.py`（代理只保留调用），再新增 OPTIONS/响应标记/请求体接线。
- 新增 `proxy_body.py`；所有后端单文件 ≤ 500 行，测试 ≤ 320 行，JS ≤ 400 行。

## 验证
- 每条先补测试并确认旧代码下变红（新增用例预计 18–22 个）。
- `env -u PYTHONHOME -u PANWEB_HOME python3 -m unittest discover -s tests -q`（基线 223，最终全绿）。
- `python3 tools/build_ui.py --check`（改 `workspace.js` 后重建 `ui/index.html`）。
- `/tmp/panweb-ci-venv/bin/ruff check --select E9,F63,F7,F82 src tools tests`。
- 不 push、不做破坏性 git 操作；四组主题提交，信息写“为什么”。

## 不在本次范围
- `target` 拆分为 `target_port`/`source_path` 的根治（会牵动 UI、统计、兼容层）。
- 未配置上游鉴权时剥离访客 `Authorization`（会破坏应用自身登录，按上述折中处理）。
- 为 panweb 自身添加通用 CORS 响应头（会放宽安全边界）。

# P0 加固任务清单

## 组 A：代理语义（commit 1）
- [x] A1 先补失败测试：静态 OPTIONS 204、端口 OPTIONS 透传、伪造转发头被剥离、CF-Connecting-IP 生效、chunked POST 透传、非法 TE=411、响应已开始后不追加 502。
- [x] A2 拆 `proxy.py` 静态服务到 `proxy_static.py`（保持行为与测试通过，单独确认）。
- [x] A3 新增 `proxy_body.py` 并在 `_forward` 接线（chunked/411/400/413）。
- [x] A4 `upstream.client_ip` + `forward_headers` 头白名单/剥离/鉴权头覆盖，`proxy.py` 改用。
- [x] A5 `do_OPTIONS` + `end_headers` 响应标记 + 异常分支收口。
- [x] A6 跑 `test_proxy.py`、`test_upstream.py`、`test_websocket.py`、新增测试；提交。

## 组 B：状态机（commit 2）
- [x] B1 先补失败测试：502/530 三次内不换 URL、隧道活着只重启代理、隧道死了才重建；恢复只挑失联/公网失败条目；改 PIN 更新 pinned 且复用 id 保留 visits/secrets。
- [x] B2 `supervisor`：`HEALTH_FAILS_LIMIT`、抽 `_health_step`、按上述分支自愈。
- [x] B3 `supervisor.recover_failing` + `ui_actions` 改为 `jobs.start`；`workspace.js` 轮询 job。
- [x] B4 `pins.write_pin` 同步 `state["pinned"]`；`_publish_port` 支持 `entry_id`；`core_set_pin` 原地替换；`stop_entry(clear_secrets=...)`。
- [x] B5 更新受影响的旧测试断言；跑 `test_recovery.py`、`test_ui_pin.py`、`test_publish_cleanup.py`、`test_jobs.py`；提交。

## 组 C：类型崩溃（commit 3）
- [x] C1 先补失败测试：`cmd_run` 返回 pages 条目时不再 TypeError，输出文件夹来源。
- [x] C2 `cli_commands._source_text` 按 kind 渲染；`cmd_publish/cmd_run/cmd_list` 改用 `entry_local_port`。
- [x] C3 跑 `test_cli.py` + 新增测试；提交。

## 组 D：安全与部署（commit 4）
- [x] D1 先补失败测试：`.nojekyll` 落盘；`~/.ssh`/`~/.aws`/`~/.config`/`~/Library/Keychains` 子目录被拒；跨进程 STOP 能释放 Forwarder；损坏 state 备份 `.corrupt-*` 并暴露 `state_issue`。
- [x] D2 `hosting._ensure_nojekyll` 接入两条发布分支。
- [x] D3 `runtime.UNSAFE_PAGE_PREFIXES` + `safety.check_pages_folder` 前缀判断。
- [x] D4 `runtime.FORWARDERS_DIR`、`Forwarder.enable_control/stop_remote`、`entries.stop_entry` 接线、启动清理陈旧 socket。
- [x] D5 `store.load_state` 隔离损坏文件 + `state_issue`；`/api/state`、`cmd_list` 提示；UI 如需要最小展示。
- [x] D6 跑相关测试；提交。

## 收尾
- [x] E1 全量测试全绿（目标 223 + 新增）。
- [x] E2 `tools/build_ui.py --check` 通过（若改 JS 需先重建）。
- [x] E3 `ruff --select E9,F63,F7,F82` 通过。
- [x] E4 中文汇报：结论、四组改动/根因、新增用例数、commit 列表、`target` 多态根治后续任务。

## 完成记录
- 组 A：42f4e4b；组 B：0f087b6；组 C：8e8086f；组 D：a8d1885。
- 全量 260 项通过，`tools/build_ui.py --check` 与 ruff CI 规则通过。
- 后续任务：`target` 多态根治（拆 `target_port` / `source_path`）见最终汇报。

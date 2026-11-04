# F3 发布历史与变更时间线 任务清单

- [x] T1 先写失败测试 `tests/test_history.py`：写入字段、敏感信息、写失败旁路、tail 大文件、CLI、API、stop/expire 埋点
- [x] T2 事件存储：`runtime.EVENTS_DIR` + `set_home`；新增 `src/panweb/events.py`（log_event / read_events / 白名单与脱敏）
- [x] T3 埋点：publish 成功/失败、pin_change、supervisor restart/url_change/error、core_stop、sweep_expired、prune
- [x] T4 CLI：`panweb history [id] --json --limit`，`cmd_history` 人读与 JSON
- [x] T5 API：`GET /api/history`（tail、过滤、limit 上限）
- [x] T6 UI：详情抽屉「时间线」区块 + `loadTimeline`，空态；重建 `ui/index.html`
- [x] T7 验证：全量 unittest（≥260）、`tools/build_ui.py --check`、ruff
- [x] T8 验收：临时状态目录发布/改 PIN/stop，`history` 完整链条 + 抽屉截图到 `docs/screenshots/history/`
- [x] T9 分主题提交（不 push）：事件存储、埋点、CLI history、API 与 UI 时间线、截图

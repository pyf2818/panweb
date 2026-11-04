# state v2 实施任务

每步完成后跑全量测试，再进下一步。

## T1 迁移与访问器（基础）
- [x] `models.py` 新增 `entry_port()` / `entry_folder()`；`entry_local_port()` 去掉 `target`。
- [x] `store.py` 新增 `STATE_SCHEMA_VERSION=2`、`migrate_entries()`、
  旧格式备份 `state.json.v1-backup`、`load_state()` 读时迁移、
  `save_state()` 写 v2 并保留未知顶层字段、`scan_legacy_target()`。
- [x] 新增 `tests/test_state_v2.py`：port/pages 两份旧数组夹具；
  断言字段、`schema_version=2`、幂等（两次 `migrate_entries` 与两次
  `load_state`）、未知字段保留、备份存在。
- [x] 全量测试。

## T2 读路径切换
- [x] `entries.entry_alive`、`entries.entry_nodes`。
- [x] `supervisor.restart_entry_proxy`、`supervisor._source_ready`。
- [x] `healthcheck.host_evidence`。
- [x] `discovery.core_discover`、`folders.quick_picks`、`proxy._app_online`。
- [x] `cli_render.source_text` 按 kind 分发。
- [x] `ui_actions._run_or_job` key 去掉 `target`。
- [x] 更新现有测试夹具：直接传给函数的 entry 用 `port`/`folder`。
- [x] 全量测试。

## T3 写路径切换
- [x] `publish._publish_port`：端口写 `port`；`serve_dir` 写 `kind=pages` + `folder`。
- [x] `publish.core_pages` 不再传 `extra={"kind","target"}`。
- [x] `publish.core_set_pin` 用 `entry_port()`。
- [x] 断言写出的 state.json 不含 `target`。
- [x] 全量测试。

## T4 doctor 遗留检查
- [x] `discovery.core_doctor` 增加 `legacy_target`。
- [x] `cli_commands.cmd_doctor` 文本输出。
- [x] 新测试：旧 state 下 count>0，v2 下 count=0。
- [x] 全量测试。

## T5 前端字段对齐
- [x] `ui/src/js/apps.js`、`core.js`、`workbench.js` 改用 `a.port`/`a.folder`。
- [x] `env -u PYTHONHOME python3 tools/build_ui.py`，再 `--check`。

## T6 收尾
- [x] `env -u PYTHONHOME python3 -m unittest discover -s tests` 全绿（382）。
- [x] `uvx ruff check --select E9,F63,F7,F82 src tools tests`。
- [x] 检查行数：所有 Python < 500，`publish.py` 389 < 400。
- [x] 分主题提交（只 add 具体文件，不 push/tag）。
- [x] 汇报：字段结构、幂等证据、访问器清单、删除分支、doctor 输出、
  测试数量、提交列表、风险（旧版读 v2、备份、前端遗漏）。

# F2 Agent 一键发布闭环 任务清单

> 规格：`docs/specs/f2-agent/spec.md`。每完成一项勾选，拆一步跑一次全量测试。

- [x] T1 规格入库：`spec.md` + `tasks.md`
- [x] T2 拆分 `publish.py`（只移动不改语义）
      - 新增 `publish_defaults.py` / `publish_text.py` / `project.py` /
        `publish_support.py`；`publish.py` re-export 旧名字
      - 实测 499 → 387 行；跑全量测试
- [x] T3 拆分 `cli_commands.py`
      - 新增 `cli_render.py` / `cli_input.py`，re-export `_source_text`；
        命令函数留在原处
      - 实测 500 → 408 行；跑全量测试
- [x] T4 `.panweb.json`
      - 新增 `project_config.py`：定位（不向上递归）、字段校验、未知键拒绝、
        权限告警、`inspect_project_config`
      - 新增 `publish_options.py`：优先级解析 + `pin_policy`
      - `core_publish/core_pages/core_run` 接入；CLI 传原始参数，不再提前合并 meta
      - `core_detect` 返回 Node `scripts` 列表，`core_run` 校验配置 script
      - `discovery.core_doctor` 增加 `project_config`，`cmd_doctor` 打印告警
      - 新增 `tests/test_project_config.py`
- [x] T5 MCP 异步与回执
      - `mcp_server.py`：发布类工具 `jobs.start` + `_await_job`
      - 新增 `get_job` 工具；`WAIT_TIMEOUT=20`
      - 完整 `inputSchema`（类型/枚举/默认值/描述）与统一回执 `_receipt`
      - single-flight 复用（key：端口 / 绝对文件夹）
      - 新增 `tests/test_mcp.py`
- [x] T6 拆分兼容测试
      - 新增 `tests/test_f2_split.py`：行数上限、`core_*` 签名、re-export 可 patch
- [x] T7 真实 MCP stdio 验证
      - 临时静态目录（含 `.panweb.json`）→ `publish_pages` → `get_job` 轮询成功
      - 不存在文件夹 → `get_job` 结构化错误
      - 回执 JSON 存 `docs/evidence/f2-agent/`；结束后停止发布
- [x] T8 验证与提交
      - 全量测试（基线 332 → 本次 365）全绿
      - `python3 tools/build_ui.py --check`
      - `ruff check --select E9,F63,F7,F82 src tools tests`
      - 分主题提交（拆分 / 配置 / MCP schema / 异步与回执 / 文档与证据），
        只 add 具体文件，不 push、不推 tag

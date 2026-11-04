# 控制台三栏科幻工作台 任务清单

> 规格：`docs/specs/console-redesign/spec.md`。实现前先过审；每项完成即勾选。

- [ ] T1 规格入库：`spec.md` + `tasks.md`（本文件）
- [ ] T2 指令解析：新增 `src/panweb/commands.py`
      - `parse_command(text, defaults=None)`
      - 动词/目标/选项/默认值/长度/控制字符/shell 形状字符/高风险端口分支
      - 先写 `tests/test_commands.py` 契约测试，再实现
- [ ] T3 API：`src/panweb/ui_actions.py` 增加 `POST /api/command`
      - 只解析，不执行；调用 `parse_command(body["text"], load_publish_defaults())`
      - `tests/test_ui.py` 末尾追加：合法指令、非法指令、Host/MIME 拒绝、状态不变
- [ ] T4 节点健康：`src/panweb/entries.py`
      - 新增 `entry_nodes(entry)`；`core_list()` 写 `e["nodes"]`
      - 覆盖 tunnel/proxy/source 的 online/offline/unknown/disabled
      - 测试放 `tests/test_commands.py`（mock `pid_alive` / `port_listening`）
- [ ] T5 布局骨架：`ui/src/index.html`、`ui/src/partials/pages.html`、
      `ui/src/manifest.json`、`ui/src/styles/console.css`、`ui/src/styles/scifi.css`
      - 三栏 shell：`aside.rail` / `main.main` / `aside.viz`
      - 导航从侧栏移到中栏顶栏；移除主题按钮；`<html data-theme="dark">`
      - 工作台页改为 `.workbench` + `.conv-log` + `.conv-composer`
      - 保留 feed/agents/term/system 原 DOM
      - 运行 `python3 tools/build_ui.py` 生成 `ui/index.html`
- [ ] T6 左栏：新增 `ui/src/js/workbench.js`
      - `renderAssets()`、`selectAsset()`、`loadAssetTimeline()`
      - 搜索过滤、运行中/停止/过期/托管状态、详情抽屉入口
      - 无应用空态
- [ ] T7 中栏：新增 `ui/src/js/commands.js`
      - `submitCommand()` → `/api/command`
      - `executeParsed()` 分派 publish/pages/run/stop/check/help
      - job 轮询步骤回显、成功回执（网址/分享/本地二维码）、失败重试
      - 高风险端口 → 提示并打开「高级发布」
      - PIN 在消息回显中打码，不写 localStorage
- [ ] T8 右栏：新增 `ui/src/js/viz.js`
      - 三节点、状态徽标、连线流动
      - PV/UV/最近访客/当前网址/隧道重建次数
      - 无数据「未知」；只消费 `/api/state` + `/api/history`
- [ ] T9 视觉与动效：`styles/scifi.css` 深空主题、网格/扫描线、
      节点呼吸、连线流动、消息入场；`prefers-reduced-motion` 全部关闭；
      设置页写明「本次控制台固定深空主题」
- [ ] T10 移动端：`≤900px` 单栏 + 左抽屉 + 底部状态抽屉、
      48px 点击区、16px 输入、顶栏标签横向滚动；
      桌面/移动各 ≥3 张截图到 `docs/screenshots/console-redesign/`
- [ ] T11 验证：
      - `python3 -m unittest discover -s tests` 全绿（基线 313）
      - `python3 tools/build_ui.py --check` 通过
      - `ruff check --select E9,F63,F7,F82 src tools tests` 通过
      - 真发布一条静态站点并停止，确认对话/右栏/时间线
- [ ] T12 分主题提交（不 push、不推 tag、只 add 具体文件）：
      布局骨架 / 左栏 / 中栏指令与对话 / 右栏可视化 / 移动端与动效 / 截图

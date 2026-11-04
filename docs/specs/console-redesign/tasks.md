# 控制台三栏科幻工作台 任务清单

- [ ] T1 规格入库：`docs/specs/console-redesign/spec.md` + `tasks.md`
- [ ] T2 指令解析：新增 `src/panweb/commands.py`（动词/端口/文件夹/选项/默认值/拒绝分支）；
      `tests/test_commands.py` 先写契约测试（解析、默认值、失败、危险字符、选项边界）
- [ ] T3 API：`ui_actions.py` 增加 `POST /api/command`（只解析）；`test_ui.py` 覆盖
      MIME/Host 校验下的解析响应与「不执行」语义
- [ ] T4 节点健康：`entries.core_list` 增加 `nodes`（代理/隧道/源，缺失为未知）；
      `test_units.py` 或 `test_commands.py` 覆盖在线/离线/未启用/未知
- [ ] T5 布局骨架：`index.html` 三栏 shell、`pages.html` 工作台页与导航标签；
      `styles/console.css` 栅格/拖动调宽/非工作台页收起右栏；构建 `ui/index.html`
- [ ] T6 左栏：`js/workbench.js` 资产列表（运行中/停止/过期/托管）、搜索、选中态、
      时间线（`/api/history`）；保留详情抽屉入口
- [ ] T7 中栏：`js/commands.js` 输入与消息流、`/api/command` → 异步 job → 步骤回显、
      成功回执（网址/分享链接/本地二维码）、失败原因 + 重试、高风险端口拒绝
- [ ] T8 右栏：节点拓扑、状态徽标、PV/最近访客/当前网址/隧道重建次数；
      只消费 `/api/state` 与 `/api/history`；无数据「未知」
- [ ] T9 视觉与动效：`styles/scifi.css` 深空主题、网格/扫描线、节点呼吸与连线流动、
      `prefers-reduced-motion` 关闭；固定深色主题并在设置页写明
- [ ] T10 移动端：≤900px 单栏 + 左抽屉 + 底部状态抽屉、48px 点击区、16px 输入；
      桌面/移动真实截图各 ≥3 张到 `docs/screenshots/console-redesign/`
- [ ] T11 验证：全量测试、`build_ui.py --check`、ruff；真实发布一条应用并验收
- [ ] T12 分主题提交（不 push、不推 tag、只 add 具体文件）

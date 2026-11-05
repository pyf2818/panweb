# 任务清单：常驻三栏 + 快捷指令区

按顺序实现；T1 可与 T2/T6 并行，T8 最后统一补契约测试。

## T1 后端预览解析（只读）

- [ ] `ui_actions.handle_get` 新增 `GET /api/preview?id=`：
  - 仅对 `core_list()` 中真实条目生效；hosted / 未知 / 已停止 → `ok:false`。
  - 只返回 `http://127.0.0.1:<proxy_port>/` 或 `http://127.0.0.1:<port>/`，绝不返回 `entry.url` 或外部地址。
  - 对目标做一次本地 HEAD（超时 2s），读 `X-Frame-Options` / `Content-Security-Policy: frame-ancestors`；返回 `embeddable` 与 `reason`。
  - 不写状态、不落盘、不记录口令。
- [ ] `tests/test_preview_api.py`：未知 id、hosted、直连端口、代理端口、XFO DENY、CSP frame-ancestors、连接失败。

## T2 中栏预览态

- [ ] `index.html` 中栏改为 `#stage`：`#stage-head`（名称 + 打开/复制/刷新/停止/重发）+ `#stage-body` + `#stage-quickbar`。
- [ ] 新增 `js/preview.js`：`renderPreview(entry)` 按 `/api/preview` 结果渲染 iframe 或降级卡；8 秒超时降级；切选中时销毁旧 iframe。
- [ ] 停止条目：不请求 iframe，显示“已停止，右栏可重发”+「打开上次链接」；云端托管：提示无本地预览。
- [ ] 复制/打开/停止/重发复用既有函数（`copyText` / `openUrl` / `vizStop` / `vizRepublish`），结果走 `aria-live`。

## T3 新建应用表单（就地）

- [ ] 左栏顶部 `＋ 新建应用` 与顶栏移动端 `＋`；点击 `openStageCreate(source)`，不跳页、不弹全屏模态。
- [ ] 中栏表单复用发布字段：来源（端口/文件夹/启动项目 + 云端托管高级）、名称、标题、说明、口令、有效期、分享。
- [ ] 端口来源复用 `/api/publish-defaults` 候选；文件夹复用文件夹选择器；项目复用 `/api/detect` 识别。
- [ ] 提交复用 `/api/publish` / `/api/pages` / `/api/run` / `/api/host*`（异步 job + 步骤展示）；失败保留表单可重试。
- [ ] 成功后 `selectedAssetId = result.id` 并回预览；口令只用一次请求参数，删除 `sessionStorage["panweb.pin"]`。

## T4 快捷指令带

- [ ] `#stage-quickbar` 常驻：发布端口 / 发布文件夹 / 启动项目 / 停止当前 / 检查一下 / 扫描端口。
- [ ] 发布类 → 打开表单并预选来源；停止当前 → 复用既有停止目标解析；检查一下 → 复用 `core_check` 调用；扫描端口 → 复用 `/api/discover`。
- [ ] 按钮走原生 button，带 `aria-label`；执行中禁用并 `aria-live` 播报。

## T5 移除对话式接线

- [ ] 删除 `partials/pages.html` 的 `#chat-log`、`#cmd-hints`、`#cmd-form`、`#cmd-input`、`#cmd-hint-line`、`#guide-card`（空态引导移到中栏 `#stage`）。
- [ ] 删除 `js/composer.js` 与 `manifest.json` 引用；移除 `commands.js` 的对话执行入口（保留被其它模块使用的目标解析函数）。
- [ ] `workbench.js` 扫描结果不再调 `fillCommand`，改为 `openStageCreate("port", port)`。
- [ ] `Cmd/Ctrl+K` 聚焦快捷带第一个 chip；`Esc` 仍关闭抽屉/弹层/通知面板。

## T6 顶栏固定、主题与通知

- [ ] `.topbar` 改 `position: sticky; top: 0; z-index`，在 `.main` 滚动容器内固定；滚动 400px 后仍可见。
- [ ] 主题控件保持三态图标 + 文本 + `aria-label`；独立占位，不被压缩到只剩图标。
- [ ] 通知控件改为「🔔 通知 + 未读徽标」按钮；面板展开时 `GET /api/history?limit=20`，条目带 `entry_id`，点击 `selectAsset(id)` 并关闭；收起丢弃。
- [ ] 未读徽标仍由 `STATE.activity` + `panweb-read-ts` 驱动，不新增轮询；`全部已读` 归零。
- [ ] 面板锚定顶栏右侧，`Esc` 与点击外部关闭。

## T7 移动端

- [ ] `≤900px`：顶栏固定且 `☰ 资产 / 主题 / 🔔 通知 / ＋新建` 均可达；中栏单栏全宽。
- [ ] 左右抽屉 + 遮罩；左抽屉顶部有「＋ 新建应用」。
- [ ] 快捷带横向滚动、页面无横向溢出；按钮 ≥48px、输入 16px。

## T8 测试与构建

- [ ] `test_ui_contracts.py`：对话元素已移除、三栏结构存在、快捷指令映射、`/api/command` 无前端引用、iframe 只用 `/api/preview` 且带 sandbox、禁嵌降级文案、通知数据源与跳转、能力映射 id 齐全、口令不落 storage、顶栏 sticky、移动断点。
- [ ] 全量基线 420 全绿 + 新增用例；`ruff check --select E9,F63,F7,F82 src tools tests`；`build_ui.py --check`。

## T9 真机验收

- [ ] 临时 `PANWEB_HOME`；发布本地静态目录 + 一个直连端口，验证三栏、预览、表单、快捷指令、通知、顶栏固定。
- [ ] 停止后右栏重发入口仍可点；若 quick tunnel 仍 429，改用本地直连条目完成预览与操作验收，并如实标注。
- [ ] 桌面 6 张 + 移动 3 张截图存 `docs/screenshots/console-three-pane/`。
- [ ] 清理临时目录、控制台、隧道；不动用户 7788 与既有隧道。

## T10 提交与汇报

- [ ] 按主题提交（预览接口 / 中栏与表单 / 快捷指令与移除对话 / 顶栏通知与移动 / 测试 / 截图），只 add 具体文件，不 push、不推 tag。
- [ ] 中文汇报：布局逐条、能力映射、iframe 安全与降级、通知来源与刷新、实测数值、测试、截图、提交、未做项与风险。

# Task Dependencies

- T2 依赖 T1（预览解析）。
- T3 依赖 T2（成功后回预览）。
- T4 依赖 T3（发布类指令打开表单）。
- T8 依赖 T1–T7。
- T9 依赖 T8。

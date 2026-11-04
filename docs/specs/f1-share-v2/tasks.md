# F1 分享页 2.0 任务清单

- [ ] T1 先写失败测试：`tests/test_share_v2.py`
  - 标题/说明校验（正常、超长、换行、控制字符）
  - CLI `--title/--desc/--qr` 解析与 core 透传落库
  - 分享页 title/desc 渲染、`<script>` 转义、默认外观不变
  - 设 PIN 时 HTML 不含口令
  - 二维码矩阵指纹（由本地 vendored qrcode.js 交叉校验）、终端渲染、内容不含 PIN
- [ ] T2 数据与校验：`models.entry_title`；`publish.normalize_title/normalize_desc`；`core_publish/core_pages/core_run/_publish_port` 接 title/desc；`core_set_pin` 保留 title
- [ ] T3 分享页：`share.build_share_page` 标题改用 `entry_title`
- [ ] T4 CLI：`publish/pages/run` 加 `--title/--desc/--qr`；`cmd_*` 透传；人类回执按需打印二维码
- [ ] T5 二维码：新增 `src/panweb/qr.py`（纯标准库，版本 1–10、EC M、终端块码）
- [ ] T6 控制台 API：三个发布接口传 title/desc；`/api/share` 复用 `normalize_desc`
- [ ] T7 控制台 UI：发布弹窗字段、提交透传、卡片/详情显示 `title || name`、说明上限 300；重建 `ui/index.html`
- [ ] T8 验证：全量 unittest（≥260）、`tools/build_ui.py --check`、ruff
- [ ] T9 验收：临时状态目录真实发布 + 浏览器截图（1440×900、390×844）到 `docs/screenshots/share-v2/`
- [ ] T10 分主题提交（不 push）：core/CLI 与存储、分享页渲染、控制台表单、二维码、截图

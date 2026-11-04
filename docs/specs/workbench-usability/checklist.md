# 验收清单：工作台可用性第二轮

## 右栏断层与重发

- [x] 已停止条目选中后右栏展示名称、上次 URL、分享链接、口令状态、有效期、PV/UV、停止时间，不再是空态。
- [x] 快照由 stop / 过期 / 清理前写入 `meta.json`，`/api/state` 下发、`/api/history` 回退，快照不含口令明文。
- [x] 「用同样配置重新发布」只传快照 port/folder/name 与可选 pin，expires/share 交给后端 `resolve_options`。
- [x] 停止、改口令、重发、自检均可从右栏发起（快照态停止/重试禁用并有说明）。
- [ ] 停止后重发成功并自动选中新条目：Cloudflare quick tunnel 429 阻塞，未能在真机完成；请求组装、任务轮询、失败提示已验证。

## 右栏分层

- [x] 链接区、状态区默认展开；历史链接、进程、最近访客默认收起。
- [x] 分组展开状态存 `panweb-dep-groups`，刷新后保持，值只含白名单布尔。
- [x] 操作区吸底，滚动右栏时位置不变；停止仍二次确认。
- [x] 最近访客位于状态区折叠内容内，选择变化时单次请求 `/api/visits`。

## 中栏

- [x] 四个快捷短语点击只填入模板并选中占位，不执行。
- [x] 输入 400ms 防抖调用 `/api/command` 显示后端 hint；占位符不触发误导性的转义错误。
- [x] `↑/↓` 回填内存历史；入栈前剥离 pin；localStorage 无口令。

## 左栏

- [x] 五个状态过滤，默认全部，刷新后保持选择。
- [x] 时间线独立可折叠，折叠状态持久化；「全局」按钮可看最近 10 条全局变更。
- [x] 排序按最近活动优先，同分按 id 稳定。
- [x] 搜索无结果有明确文案与「清除筛选」。

## 空态与无障碍

- [x] 零条目中栏显示三步引导，扫描本机端口可触发既有发现逻辑并列出候选。
- [x] `Cmd/Ctrl+K` 聚焦中栏输入；`Esc` 关闭二维码弹层与移动抽屉。
- [x] 复制成功通过 `#sr-live`（aria-live polite）播报。
- [x] 快捷短语、过滤 chips、折叠按钮均为可聚焦原生 button，带可访问名称。

## 工程约束

- [x] `python3 -m unittest discover -s tests` 420 项全绿（基线 399）。
- [x] `ruff check --select E9,F63,F7,F82 src tools tests` 通过。
- [x] `python3 tools/build_ui.py --check` 通过。
- [x] 未改动 `publish.py`、`cli_commands.py`、`share.py`；未新增高频轮询；无框架/npm/CDN。

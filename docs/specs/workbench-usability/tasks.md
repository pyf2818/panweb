# 任务清单：工作台可用性第二轮

按顺序执行，每项完成后跑对应测试；1、2 先做。

## T1 快照存储（后端）

- [x] 新增 `src/panweb/last_deploy.py`：`snapshot_entry` / `remember_last` / `load_snapshots` / `find_snapshot`，去重签名、上限 5、只存布尔口令状态。
- [x] `entries.core_stop`：stop 前采集 visits + domain 并写快照。
- [x] `lifecycle.sweep_expired` / `prune_dead_entries`：过期/清理也写快照（reason 区分）。
- [x] `/api/state` 返回 `last_deployments`，并按运行中同签名过滤。
- [x] `/api/history` 对已删除条目回退快照 `build_detail`，附 `from_snapshot/stopped_at/stop_reason`。

## T2 右栏分层 + 吸底 + 最近访客

- [x] `index.html` 右栏改五组结构；链接/状态默认展开，历史/进程/访客默认收起；操作区吸底。
- [x] 新增 `js/depgroups.js`：分组切换、`aria-expanded`、`localStorage["panweb-dep-groups"]` 只存布尔 JSON。
- [x] 最近访客：选择变化时单次 `/api/visits?id=`，停止条目显示「已随停止清理」。
- [x] 1440×900 首屏可见：名称/状态、两链接、二维码、关键状态、操作区。

## T3 已停止/已到期视图与重发

- [x] 新增 `js/lastpub.js`：`renderStopped`、`vizRepublish`、`vizCheckSource`、快照态按钮语义。
- [x] 重发只用快照 port/folder/name + 可选 pin；expires/share 留空复用后端记忆；成功后选中新条目。
- [x] 停止/重试在快照态禁用并说明；改口令=重发并设口令；自检=检查源状态（discover/detect）。

## T4 中栏可发现性

- [x] 快捷短语改「发布端口/发布文件夹/停止当前/检查一下」，填模板并选中占位，不执行。
- [x] 新增 `js/composer.js`：400ms 防抖调 `/api/command` 显示后端 hint；`↑/↓` 内存历史，`stripPin` 剥离口令，不写 localStorage。
- [x] 提交时把剥离口令后的指令入内存历史。

## T5 左栏过滤 / 时间线 / 排序 / 空搜索

- [x] 五个过滤 chips（默认全部）+ `panweb-asset-filter` 记忆。
- [x] 合并 apps + 快照 + hosted；稳定排序（运行中 started 倒序、快照 stopped_at 倒序）。
- [x] 时间线独立折叠块，未选中时 `/api/history?limit=10` 全局；`panweb-rail-timeline` 布尔；标题栏加「全局」按钮可在有选中时查看全局最近 10 条。
- [x] 搜索无结果提示 + 清除筛选。

## T6 空态引导 + 无障碍

- [x] 中栏三步引导卡（零条目）+ 左右栏扫描入口；`scanPorts()` 用 `/api/discover`。
- [x] `Cmd/Ctrl+K` 在 apps 页聚焦 `#cmd-input`；`Esc` 关闭抽屉与 `.overlay.show`。
- [x] 复制 `aria-live` 播报（`#sr-live`），视觉不变。
- [x] chips/折叠/过滤的可访问名称与键盘可达。

## T7 测试

- [x] `tests/test_last_deploy.py`：快照字段与无密钥、去重/上限、运行中过滤、history 回退、重发配置来源（resolve_options 复用记忆）、stop 前采集访问量。
- [x] `tests/test_ui_contracts.py`：分组持久化白名单布尔、过滤分组、命令提示复用 `/api/command`、快捷模板占位、↑ 历史不含 pin/不写 localStorage、空态三步与扫描、aria-live/快捷键、重发不传 expires/share、口令输入不落 storage。
- [x] 全量测试与 ruff、build --check。

## T8 真机验收与截图

- [x] 临时 `PANWEB_HOME` 启动控制台；发布端口 + 文件夹，停止一个，验证快照、重发、源检查。
- [ ] 停止后用右栏重发成功（Cloudflare quick tunnel 持续 429，外部阻塞；请求组装/任务轮询/失败提示已验证）。
- [x] 桌面 4 张、移动 2 张截图存 `docs/screenshots/workbench-usability/`。
- [x] 实操：折叠刷新保持、↑ 回填、localStorage 无口令、Cmd+K/Esc、aria-live。
- [x] 停掉所有发布、清理隧道与临时目录。

## T9 提交与汇报

- [x] 按主题拆提交（后端快照 / 右栏分层 / 中栏 / 左栏 / 空态无障碍 / 测试 / 文档截图），只 add 具体文件，不 push。
- [x] 中文汇报：结论、逐条落地、重发来源优先级、存储内容、历史链接与访客位置、快捷键与 aria-live、测试与截图、提交列表、未做项与风险。

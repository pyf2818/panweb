# panweb 架构设计

本文描述 panweb 1.6 的代码结构、依赖规则、运行模型与商业许可边界。目标是：
后端按职责分包、单文件不超过约 450 行、前端样式与脚本可独立维护，同时保留
“本机运行、离线可用、单条命令发布”的交付方式。

## 1. 设计原则

1. **单向依赖**：底层不知道上层。`runtime → store → processes → tunnel → domain/publish → ui/cli`。
2. **显式状态**：所有跨进程状态都在 `~/.panweb` 下，使用原子写与跨进程文件锁。
3. **副作用集中**：进程启动、隧道创建、文件删除只出现在明确的服务/生命周期模块。
4. **安全默认**：控制台只监听回环地址并校验 Host/Origin；发布默认直连，需要口令/统计/分享时才走内置代理。
5. **可退出**：任何后台进程都能通过状态文件与 PID+命令行双重校验被回收。
6. **可离线**：运行时不依赖 panweb 云服务；许可是离线签名文件，不做联网校验。

## 2. 目录布局

```
panweb                      # 薄启动器：把 src/ 加入 sys.path，调用 panweb.cli:main
src/panweb/
  __init__.py               # 版本号
  __main__.py               # python -m panweb
  runtime.py                # 路径、常量、资源根目录、自启动命令
  errors.py                 # PanwebError / TunnelError
  cliio.py                  # JSON/人类可读输出契约
  store.py                  # 私有目录、原子写、跨进程锁、state/meta/activity/domain
  models.py                 # 纯数据辅助：公开 URL、分享 URL、回源端口
  processes.py              # PID 校验、端口探测、cloudflared 发现、孤儿清理
  tunnel.py                 # 快速隧道启动、公网可达性验证
  pins.py                   # 口令哈希、旧格式迁移、失败限流
  visits.py                 # 匿名访问记录、聚合、系统通知
  share.py                  # 分享页模板与渲染、分享令牌
  static.py                 # 路径穿越/符号链接/dotfile 防护
  safety.py                 # 文件夹发布边界、上传路径校验
  lifecycle.py              # 有效期解析、到期收回、陈旧条目清理
  forwarder.py              # TCP 转发器、预热隧道池
  domain.py                 # Cloudflare 命名隧道固定域名
  entries.py                # 发布条目注册/停止/存活/列表/菜单栏状态、上游兼容设置
  upstream.py               # 上游兼容层：Host 模式、代访客注入凭据、转发头构造
  healthcheck.py            # 发布后的访客视角自检（首页/资源/WebSocket）与取证自动修正
  term.py                   # 控制台里的真终端：PTY 会话、非阻塞读写、SSE 画面推流
  folders.py                # 本机目录浏览：控制台「选文件夹」的数据源（只列目录，不读内容）
  publish.py                # 发布端口/静态页/自动启动项目、代理子进程
  discovery.py              # 可发布应用发现、doctor
  supervisor.py             # 健康巡检、隧道/代理自愈、启动清理
  convert.py                # Markdown/Excel → HTML、站点整理
  hosting.py                # GitHub Pages 云端托管
  agents.py                 # 本机 Agent 技能安装、终端可执行的 Agent 白名单与命令行
  installer.py              # 一键安装 cloudflared
  menubar.py                # Swift 菜单栏构建
  packaging.py              # 自包含 macOS App 构建
  console.py                # 控制台守护进程
  system.py                 # 系统全景、离线打包
  diagnostics.py            # 脱敏诊断包：字段掩码 + 出包前自审（混进密钥就拒绝）
  codesign.py               # Developer ID 签名与苹果公证（无凭据退回 ad-hoc）
  update.py                 # 检查 GitHub Releases、按架构挑包、许可窗口内取回升级包
  mcp_server.py             # MCP stdio 服务
  proxy.py                  # 内置代理子进程：口令门禁、分享页、转发、WebSocket、静态服务
  ui_server.py              # 控制台 HTTP 服务与路由
  ui_actions.py             # 控制台 GET/POST 路由处理器
  ui_context.py             # 控制台进程内共享对象（通知器句柄）
  licensing.py              # 买断制离线许可（试用/激活/设备/更新权益）
  cli_commands.py           # 各命令的输出渲染（JSON / 人类可读）
  cli.py                    # argparse 定义与调度（唯一入口 main）
ui/src/                     # 前端源码：6 CSS + 10 JS + 2 partials + index + manifest
ui/index.html               # 构建产物（文件头有「请勿直接编辑」横幅）
ui/vendor/                  # 第三方前端库（qrcode.js、xterm.js + fit/canvas 插件，原样引入不拆改）
site/                       # 项目介绍页（独立静态站：index + 3 CSS + 4 JS，可用 panweb pages 发布）
tools/build_ui.py           # 组装前端为单文件
tools/build_zipapp.py       # 构建单文件分发 dist/panweb.pyz
tools/build_dmg.py          # macOS 安装包：调用 install-app 造 App，再 hdiutil 打成 dmg
tools/license_tool.py       # 卖家侧离线许可签发
tests/                      # 单元、CLI、代理、子进程集成、控制台安全、许可、构建与体积守卫
docs/architecture.md        # 本文
docs/licensing.md           # 许可运营手册
```

## 3. 依赖分层

```
                 cli.py ── cli_commands.py      ui_server.py ── ui_actions.py ── ui_context.py
                 mcp_server.py（AI 客户端入口，复用同一批 core_* 函数）
                 ├── system.py / packaging.py / console.py / installer.py
                 ├── diagnostics.py / update.py ── licensing.py
                 ├── codesign.py（只在构建期被 tools 调用）
                 ├── supervisor.py ── domain.py
                 ├── publish.py ── entries.py ── lifecycle.py
                 │      ├── healthcheck.py ── upstream.py
                 │      ├── forwarder.py ── tunnel.py
                 │      └── pins.py / share.py
                 ├── discovery.py
                 ├── term.py ── agents.py / processes.py
                 ├── folders.py ── safety.py
                 ├── hosting.py ── convert.py
                 ├── agents.py / menubar.py
                 ├── proxy.py（独立子进程入口）
                 └── licensing.py
基础层：runtime.py · errors.py · cliio.py · store.py · processes.py · models.py
        static.py · safety.py · browser.py · pins.py · visits.py
```

规则：

- `runtime`、`errors` 不导入任何业务模块。
- `store` 只依赖 `runtime`；不做网络、不启动进程。
- `processes` 可依赖 `store`（读取内部端口），但不得依赖发布/控制台。
- `publish` 不导入 `supervisor`/`ui`；自愈逻辑由 `supervisor` 单向调用。
- `domain` 不导入 `entries`；只通过 `models.entry_local_port` 与状态文件取数据。
- `upstream` 只做"请求头怎么发给应用"这一件事：不启动进程、不读写隧道，密钥只向
  `store` 的 secrets 目录要。`proxy`（子进程）与 `healthcheck` 共用它，两边看到的
  Host/凭据语义永远一致。
- `healthcheck` 单向调用 `entries`/`upstream`：自检能改条目的 `host_mode` 与 `check`
  结论，但绝不反过来被 `publish` 调用链依赖——发布只负责 `schedule_check()` 扔进后台线程。
- `term` 只认识三件事：白名单里的 Agent id、主人指定的工作目录、PTY 两头的字节。
  一条隐性契约：PTY 的行列表数就是子进程重绘时用的行列表数，所以前端在打开、切回、
  布局变化后都要把网页算出来的格数推回去（`TIOCSWINSZ`）——只靠 xterm 的 `onResize`
  不够，刷新后网页尺寸没变而 PTY 还记着旧尺寸，画面就会错位。
  它不解析画面内容、不实现模型，也不接受界面传来的可执行文件路径或命令行——界面上进来
  的是「选哪个 Agent」和键盘。真终端以主人身份运行，能改本机文件、能执行发布命令，
  所以控制台只监听回环、只认本机 Host/Origin，并且最多四个并发、退出即回收子进程。
- `diagnostics` 与 `update` 都受许可约束，但方向相反：前者**往外拿**（导出前递归掩码
  含 token/password/secret/pin/key/cookie/authorization 的字段，跳过 `secrets`/`pins`/
  `visits` 三个目录，打包后再读一遍 zip 自审，发现漏网就抛错并删掉坏包）；后者**往里放**
  （只走 HTTPS，先问 `licensing` 的 1 年更新窗口，过期就 `license_expired` 拒绝，
  落地后按 Release 记录核对大小、算 SHA-256，然后只 `open` dmg —— 绝不替换正在运行的
  App 或 site-packages，替换这一步留给人拖拽）。
- `codesign` 只在构建期用：没有 `PANWEB_SIGN_IDENTITY` 就退回 ad-hoc 并如实写进
  「安装说明」，签名失败不当作构建失败（开发机不该被凭据卡住）。
- `cli.py` 只定义参数并调度，`cli_commands.py` 只渲染输出，二者都不含业务逻辑；
  控制台与打包命令按需延迟导入，避免每次 CLI 启动加载整条 UI/代理链。
- 业务能力只写在 core 模块，UI/CLI 复用同一组 `core_*` 函数，不复制逻辑。
- 循环依赖靠 `ui_context`（进程内共享句柄）拆开，不用函数内 import 绕。
- 单文件体积由测试守住（`tests/test_build.py`）：后端 ≤500、前端模块 ≤400、
  工具 ≤220、测试 ≤320、启动器 ≤50 行；`ui/index.html` 与 `ui/vendor/` 是豁免的生成物/第三方库。

## 4. 运行模型

### 4.1 进程拓扑

```
panweb (CLI / App)
  ├─ cloudflared 快速隧道 ──> 127.0.0.1:目标端口
  │                            └─ 直连发布（无口令/无统计）
  ├─ cloudflared 快速隧道 ──> 127.0.0.1:代理端口
  │                            └─ ProxyHandler（口令、统计、分享页、静态/WS）
  ├─ cloudflared 命名隧道 ──> 127.0.0.1:固定域名转发器
  │                            └─ Forwarder ──> 当前绑定的应用
  ├─ 预热隧道 + Forwarder（控制台常驻，发布时秒级取用）
  └─ 控制台 UiHandler（仅 127.0.0.1:7788）
```

所有 cloudflared、代理、控制台守护进程都使用 `start_new_session=True`，CLI 退出不影响；
状态中保存 PID，回收时同时校验命令行，避免 PID 复用误杀。

### 4.2 发布状态机

```
未发布
  └─ publish/pages/run
       ├─ 直连：cloudflared → 应用端口
       └─ 代理：cloudflared → ProxyHandler → 应用端口 / 静态目录
            └─ 可选：口令、分享令牌、有效期

发布中 ── 到期/stop/控制台退出(仅界面) ──> 已收回
发布中 ── 代理死亡 ──> 重启代理（网址不变）
发布中 ── 隧道 502/530/失联 ──> 重建隧道（网址可能变化）
发布中 ── 应用端口不再监听 ──> 保持条目，等待应用恢复（不空转重建）
```

### 4.3 数据文件

| 文件 | 内容 | 权限 |
| --- | --- | --- |
| `state.json` | 发布条目（id/name/url/pid/proxy_port/share_token/expires_at/host_mode/auth_kind/check…） | 600 |
| `state.lock` | 跨进程 flock | 600 |
| `meta.json` | 通知开关、owner grace、累计停止数 | 600 |
| `activity.json` | 最近 200 条操作 | 600 |
| `secrets/*.pin` | 加盐 SHA-256 口令与会话 | 600 |
| `secrets/*.auth.json` | 上游凭据（bearer/basic/自定义头）；只在代理进程内读取 | 600 |
| `secrets/visits.key` | 访客 IP 的 HMAC 密钥 | 600 |
| `visits/*.jsonl` | 匿名访问记录（无原始 IP/UA） | 600 |
| `domain.json` | 固定域名隧道状态 | 600 |
| `pool.json` | 预热隧道 PID/端口（异常退出回收） | 600 |
| `license.json` | 离线许可/试用状态 | 600 |
| `logs/*.log` | 隧道/代理/域名/控制台日志（诊断包只取每个尾部若干 KB） | 目录 700、文件 644 |
| `packs/*.zip` | `panweb pack` 导出的离线静态包 | 目录 700、文件 644 |
| `reports/*.zip` | `panweb report` 导出的脱敏诊断包 | 目录 700、文件 644 |
| `update/*` | `panweb update apply` 取回的升级包（下载先写 `.part`，核对通过才改名） | 目录 700、文件 644 |

路径统一由 `runtime.set_home()` 计算，测试可指向临时目录。

### 4.4 访客视角自检

隧道 200 只代表 cloudflared 连上了本机端口，不代表访客打得开应用。发布后
`healthcheck.schedule_check()` 在后台线程按访客走一遍：

```
发布完成 ──> 后台自检（每条发布去重，约 20 s 预算）
              ├─ 首页：公网 URL 的状态码、重定向链、是否停在「加载中」
              ├─ 资源：从 HTML 里抽样 JS/CSS，命中 404/未编译源码即判"资源缺失"
              ├─ WebSocket：裸 TLS 握手，101 才算通
              └─ 取证修正：疑似 Host 校验 → 用两种 Host 回源比对 →
                          仅当真被拒才切 host_mode，切完仍拒则回滚
              结论写入 entry["check"] = {verdict, summary, signals[], fixes[], ts}
```

`healthcheck.await_check()` 让命令行也一定给结论（拿不到就自己跑一次），控制台抽屉与
分享页读的是同一份 `entry["check"]`——`verdict=blocked` 时分享页把状态降级成
「主人自检未通过」，避免绿色「在线」和提示文字互相打脸。

结论要归因准确，否则会把人引到错误的方向上：

- 本机解析不到网址（DNS 慢或被污染）但边缘 IP 直连有响应 → `dns_slow`（warn），
  说"访客侧多半能打开"，而不是报死。
- HTTP 530 是 Cloudflare 边缘自己造的，代表这台机器没有活着的连接器 → `tunnel_down`，
  指向「恢复通道/重新发布」，不冤枉应用；500/502 才归给 `server_error`。

## 5. 安全边界

| 边界 | 措施 |
| --- | --- |
| 控制台 | 仅回环监听；Host/Origin 白名单；POST 必须 `application/json`；CSP；不发布自身端口 |
| 静态发布 | `realpath + commonpath`；拒绝 dotfile、根外符号链接、系统根目录；只读；SPA 回退不绕过防护 |
| 口令 | 随机盐 + SHA-256；常量时间比较；10 分钟 8 次失败限流；Secure/HttpOnly/SameSite Cookie |
| 分享页 | 令牌常量时间比较；HTML 全量转义；`noindex`；统计路径脱敏；访客提示只说明"会遇到什么"，不泄露本机端口/路径 |
| 访客统计 | IP 经持久 HMAC 后截断；不存 UA/查询串；文档请求才计数；机器人过滤 |
| 上游兼容 | `host_mode` 默认 `loopback`（本机应用靠 Host 校验挡 DNS 重绑定，不替访客伪造公网 Host）；改 `tunnel` 需显式设置。两者只在代理模式有意义：直连发布的链路里没有 panweb，`core_compat` 的写操作会返回 `not_supported` 并给出切代理的做法，界面同步置灰 |
| 上游凭据 | 只落 `secrets/<id>.auth.json`（600），代理进程内读取；`state.json`/`/api/state`/CLI/菜单栏/分享页只出现 `auth_kind` 与掩码标签，永不回显密钥；头名/值经 RFC 7230 校验，拒绝 CR/LF 与控制字符，禁止覆盖 Host/Connection/Upgrade/Content-Length |
| 隧道 | 只出站连接到 Cloudflare；本地源站绑定 127.0.0.1。QUIC（UDP 443）被网络静默丢包时会自动改走 `--protocol http2`，避免"网址拿到了但永远 530" |
| 子进程 | argv 数组，不经过 shell；PID + 命令行双重校验后终止 |
| 目录选择器 | 只列目录、不列文件与隐藏项、不跟随符号链接、单次上限 400 条；路径由本机 realpath 解析，界面传不进任意读文件的能力（读内容仍走静态发布那套边界） |
| 本机 Agent 终端 | 只有回环控制台能调用；Agent 二进制按固定白名单（Claude Code / Codex / OpenCode）从 PATH 解析，界面传不进可执行文件路径与命令行，只传「选哪个 Agent + 工作目录 + 键盘字节」；工作目录必须是本机已存在目录（`realpath` 后使用）；并发 4 个、画面缓冲每端 300KB 截尾、单次写入 32KB 上限、尺寸钳制在 20-400 列 × 6-200 行；关闭会话先终止子进程，仍活着就 `killpg` 整组；控制台退出时统一回收，不留孤儿。Agent 仍以主人身份执行——它能动本机，这是这个功能的定义而不是漏洞 |
| 诊断包 | 递归掩码含 token/password/secret/pin/key/cookie/authorization 的字段；跳过 `secrets`/`pins`/`visits`；出包后重新读一遍 zip 自审，混进未脱敏字段即报错并删除坏包 |
| 更新 | 数据源固定为 GitHub Releases（`PANWEB_RELEASE_REPO` 可覆盖）；先查许可的 1 年更新窗口，过期拒绝（`license_expired`）；只接受 `https://` 资源；落地核对 Release 记录的大小，不符即丢弃；打印 SHA-256 供比对，真正的信任链是 Developer ID 签名与苹果公证；**不替换正在运行的 App** |
| 许可 | 离线 RSA 签名；机器指纹哈希；不联网、不采集使用数据 |

## 6. 前端架构

`ui/src/` 按职责拆分：

```
ui/src/index.html          # 语义骨架，引用占位符
ui/src/partials/           # 主区页面与浮层（pages/overlays）
ui/src/styles/base.css     # 变量、重置、排版、主题
ui/src/styles/layout.css   # 拖拽手柄、侧栏、顶栏
ui/src/styles/components.css # 按钮、卡片、统计、应用卡、许可
ui/src/styles/overlays.css # 弹窗、抽屉、Toast、命令面板
ui/src/styles/terminal.css # 终端页：整幅布局、工具条、xterm 容器配色
ui/src/js/core.js          # 状态、API、轮询、主题、工具、渲染
ui/src/js/apps.js          # 动作、发布、详情抽屉、分享/统计
ui/src/js/sharing.js       # 分享图、固定域名、安装、停止
ui/src/js/license.js       # 试用/激活/解除与状态展示
ui/src/js/workspace.js     # 三栏伸缩、页面切换、系统、更新检查、命令面板
ui/src/js/diagnose.js      # 访客视角自检结论渲染、host_mode 与上游凭据设置
ui/src/js/term.js          # 真终端页：xterm.js 挂载、尺寸回写 PTY、键盘直通、SSE 续播
ui/src/js/picker.js        # 文件夹选择器：翻本机目录回填路径（终端 / 发布文件夹 / 启动项目）
ui/src/js/fx.js            # 氛围层：隧道流线粒子（在线数=密度、新动态=脉冲），终端页与隐藏标签停笔
ui/src/styles/decor.css    # 氛围与装饰：光带/颗粒/卡片抬升/标题饰/入场浮起/焦点环
ui/src/js/boot.js          # 启动
ui/src/manifest.json       # 组装顺序
```

`tools/build_ui.py` 读取 manifest，把 CSS/JS 内联进单个 `ui/index.html`，再按
`LIBRARY_SLOTS` 注入第三方库（qrcode.js、xterm.js 与 fit/canvas 插件、xterm 样式，
都在 `ui/vendor/`）；`--check` 用于 CI。运行期仍然只分发一个 HTML，无构建步骤依赖。

**氛围层**（`fx.js` + `decor.css`）的契约：它是背景，不是主角。三层由远到近是
光带（`body::before`，z-index -3）→ 颗粒质感（`body::after`，-2）→ 隧道粒子（`#fx`，-1），
全部 `pointer-events: none`，卡片仍是不透明表面，粒子只从缝隙与半透明侧栏后透出来。
粒子画的是链路本身：本机节点（左下）→ Cloudflare 边缘（右上），在线应用数决定流密与亮度，
新动态从本机放一圈脉冲。开销封死：帧率上限 30fps、DPR 上限 1.6、粒子数按视口面积 14-44 个，
终端页（`body[data-page="term"]`）淡出到 0 后 `cancelAnimationFrame` 彻底停笔并清空画布，
标签页隐藏由浏览器自然挂起、回前台时重置时基不补画一大帧，`prefers-reduced-motion` 下
只画一张静构图、CSS 动画全部关闭。它不联网、不读 API，`fx.sync(STATE)` 只吃已有的状态对象。

## 7. 买断制许可（离线）

商业模型：**一次买断，永久使用；含 1 年更新；默认 2 台设备**。

- 试用：首次启动写 `license.json`，默认 14 天；到期后进入只读/提醒模式。
- 激活：`panweb license activate <key>`，密钥是 Base64 的签名载荷：
  `{license_id, product, edition, issued_at, updates_until, devices, email_hash}`。
- 校验：纯 Python RSA PKCS#1 v1.5 + SHA-256，公钥内置于 `assets/license_public_key.pem`
  或 `PANWEB_LICENSE_PUBKEY`；不联网。
- 设备绑定：`machine_id` 为硬件 UUID/主机名/用户名的 SHA-256 截断；许可文件记录本机指纹，
  默认 2 台；换机需在旧机 `deactivate` 或由卖家重签。
- 更新权益：`updates_until` 之后仍可运行当前版本，但不承诺新版本；程序版本不反向限制。
- 开发模式：未配置公钥时视为 `development`，不限制功能；公开发行前由所有者生成密钥并内置公钥。
- 支付：Lemon Squeezy / Paddle 等 Merchant of Record 完成收款与税务；panweb 不建账号体系、
  不存支付信息。卖家侧用 `tools/license_tool.py` 离线签发。

免费/开源自托管与商业发行是两条构建线：仓库默认不带私钥，构建发行版时才注入公钥并启用强制校验。

## 8. 打包与分发

- **源码运行**：`./panweb` 薄启动器 + `src/panweb` + `ui/index.html`。
- **macOS App**：`panweb install-app` 复制 `src/panweb`、`ui`、`skill`、`assets`、cloudflared，
  生成 `~/Applications/panweb.app`；launcher 设置 `PANWEB_RESOURCE_ROOT` 与入口路径。
  Python 解释器不随包分发，运行时使用系统 `python3`；没有命令行工具时 launcher 会引导安装。
- **macOS 安装包**：`python3 tools/build_dmg.py`（`make dmg`）先用同一条 `install-app` 命令在临时
  目录造 App，再用 `hdiutil` 打成 `dist/panweb-<版本>-<架构>.dmg`（UDZO，内含拖拽用的
  `Applications` 软链与安装说明）。安装包只是构建产物，`dist/`、`*.dmg` 与 `keys/` 都在
  `.gitignore` 里。签名由 `codesign.py` 负责：**没有配置身份就退回 ad-hoc**（首次打开需右键
  「打开」），配了 `PANWEB_SIGN_IDENTITY` 就按"先里后外"签 `panweb-launcher` 与内置
  `cloudflared`，再带 entitlements 签 bundle；只有真用 Developer ID 签名时才走苹果公证
  （`notarytool submit --wait` → `spctl --assess` → `stapler staple`），「安装说明」与构建
  日志都会如实反映当前到底签成没签成——不拿 ad-hoc 冒充已公证。
- **单文件 zipapp（可选）**：`tools/build_zipapp.py` 生成 `dist/panweb.pyz`；
  `runtime.read_resource()` 支持从 zip 读取 UI/模板，技能目录回退到已安装副本。
- 运行期不需要 pip 依赖；Python 标准库 + cloudflared 即可。

### 8.1 环境变量

子进程（内置代理、控制台守护）由 `runtime.self_command()` + `runtime.self_env()` 拉起，
`PANWEB_HOME`、`PANWEB_RESOURCE_ROOT`、`PANWEB_ENTRYPOINT`、`PANWEB_CLOUDFLARED` 会一并继承，
所以父进程与代理子进程看到的始终是同一套状态目录。

| 变量 | 作用 |
| --- | --- |
| `PANWEB_HOME` | 状态目录（默认 `~/.panweb`）；测试与便携模式的隔离开关 |
| `PANWEB_RESOURCE_ROOT` | `ui/`、`skill/`、`assets/` 的资源根；App 由 launcher 指定 |
| `PANWEB_ENTRYPOINT` | 可再次执行的 panweb 入口（zipapp/App 内自拉起用） |
| `PANWEB_CLOUDFLARED` | 指定 cloudflared 二进制 |
| `PANWEB_TUNNEL_PROTOCOL` | 强制隧道传输：`auto` / `quic` / `http2`；不设则探测 UDP 443 |
| `PANWEB_LICENSE_PUBKEY` | 覆盖内置验签公钥路径 |
| `PANWEB_LICENSE_OFF` | 关闭许可门禁（开源/自托管构建线） |
| `PANWEB_TRIAL_DAYS` | 试用天数（默认 14） |
| `PANWEB_MACHINE_ID` | 覆盖机器指纹（仅测试） |
| `PANWEB_SIGN_IDENTITY` | Developer ID 签名身份；不设则 ad-hoc，签名失败也不阻断构建 |
| `PANWEB_NOTARY_PROFILE` | 公证用 keychain profile（优先）|
| `PANWEB_APPLE_KEY_ID` / `PANWEB_APPLE_ISSUER_ID` / `PANWEB_APPLE_P8` | 公证 API 密钥三件套（profile 不存在时用） |
| `PANWEB_RELEASE_REPO` | 更新来源仓库 slug（默认 `pyf2818/panweb`） |
| `PANWEB_DEBUG` | 出错时抛出栈而非 JSON 错误 |

## 9. 测试策略

| 层 | 覆盖 |
| --- | --- |
| 单元 | 路径穿越、dotfile、符号链接、口令哈希/迁移、状态锁、有效期、分享 URL、访问聚合、通知去重 |
| CLI 合约 | JSON 错误结构、退出码、版本、help 子命令、危险目录拒绝、`check` 阻塞时退出 1、`compat` 输出不含密钥 |
| 代理 | 分享页 OG/转义/令牌、分享页登录、过期 410、口令 Cookie、静态服务 |
| WebSocket | 最小回显后端 + 裸客户端：101 握手原样透传、文本帧双向、ping/pong、转发头清洗 |
| 资源归还 | `duplex()` 两端 socket 必须关闭（隧道/代理按访客数复用，漏 fd 就是漏稳定性） |
| 上游兼容 | `test_upstream.py`：转发头构造（Host 模式、WebSocket 保留 Upgrade/Connection）、凭据归一化与 CR/LF 注入拒绝、密钥文件权限、真实代理子进程端到端代填 |
| 访客自检 | `test_healthcheck.py`：结论判定（首页/资源/未编译源码）、裸 TLS WebSocket 探测、Host 取证修正与回滚；`test_selfcheck.py`：走真实代理子进程验证修正传播与结论落盘 |
| 隧道传输 | `test_tunnel.py`：QUIC 探测结果按进程缓存、探测不通时命令行带 `--protocol http2`、`auto` 不改命令行、`PANWEB_TUNNEL_PROTOCOL` 可强制 |
| 目录选择器 | `test_folders.py`：只列子目录（隐藏/文件/符号链接都排除）、排序与截断计数、主目录不可发布、坏路径与 NUL 拒绝；`test_ui.py`：`/api/folders` 需要本机 Host，缺 Host 直接 403 |
| 真终端 | `test_term.py`：假 Agent 跑在 PTY 里，验证 argv 白名单（没有 shell、没有一次性开关）、逐字回显、`TIOCSWINSZ` 真的传到子进程、退出码、缓冲上限与游标补发、写已退出终端被拒、关闭回收子进程、并发上限不误杀活的；`test_term_stream.py`：SSE 帧的游标/心跳/断线续播与 `gap` 上报；`test_ui.py`：`/api/term/*` 路由与旧的 `/api/agent/*` 已下线 |
| 自愈与回收 | `test_recovery.py`：死隧道不进取用池（三次都死就如实报死）、恢复未验证通过就不写状态、正在服务的隧道被收编、孤儿快速隧道被回收但**在用的三条都不动**（后面挂着活代理的、状态里引用的、父进程还在的） |
| 诊断包 | `test_diagnostics.py`：包内容齐全、凭据永不入包、日志只取尾部、自审能拦下未脱敏字段并删掉坏包、`--out` 生效、裸装（无状态文件）也能出包 |
| 签名与公证 | `test_codesign.py`：无身份退回 ad-hoc、有身份时先内后外且失败不越级、dmg 只签外层、凭据缺失即跳过公证、keychain profile 优先于 API 三件套、不完整的三件套被忽略、submit→assess→staple 顺序 |
| 更新 | `test_update.py`：版本号解析（`v` 前缀、补零、乱串归零、1.10 > 1.9）、按架构挑包与 `.pyz` 兜底、同版本不算新、404/断网/返回结构异常都如实报错、许可窗口过期拒绝下载、下载大小不符即丢弃、只接受 `https://`、SHA-256 正确、失败不留 `.part` |
| 控制台 | Host/Origin 拒绝、JSON Content-Type、自身端口拒绝发布、旧应用补分享令牌、`/api/compat` 不回显密钥、`/api/check` 落盘 |
| 构建 | `build_ui.py --check` 产物一致、生成物横幅、模块体积上限、全模块可导入、zipapp 可执行 |
| 集成 | 真实代理 + 临时静态目录 + 临时 HOME；隧道相关使用 fake cloudflared；`_spawn_proxy` 拉起的子进程转发、分享页与口令门禁 |

CI 在 push/PR 运行全部测试与前端产物一致性检查。

## 10. 演进路线

1. **1.5**：完成分包、前端模块化、离线许可与回归。
2. **1.5.x**：上游兼容层（`host_mode` + 代访客注入凭据）与发布后的访客视角自检——
   把"能发布"变成"打得开"：复杂应用不再只有一个壳，结论同时出现在命令行、控制台抽屉
   与分享页。
3. **1.6**：控制台里的真终端（PTY + xterm.js）、目录选择器、版本错配提示、
   启动回收孤儿隧道、一键诊断包、macOS 签名与公证、检查更新与升级包取回。
   剩下的是发行侧的收尾：真实 Developer ID 凭据、`keys/` 许可密钥对的正式归属、
   GitHub Release 首发（有了 Release，`panweb update` 才真正有东西可查）、LICENSE/EULA。
4. **2.0**：可插拔隧道引擎、团队/多设备管理（不引入云端账号，除非重新评估隐私边界）。

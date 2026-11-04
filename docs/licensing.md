# panweb 买断许可运营手册

本文是给**发行者/卖家**看的操作说明，不是用户文档。核心原则：许可离线校验、
不建 panweb 账号、不收集设备信息、私钥永不进入仓库或发行包。

## 1. 商业模型

| 项 | 默认值 | 说明 |
| --- | --- | --- |
| 授权方式 | 一次买断 | 永久使用当前版本 |
| 试用 | 14 天 | 首次启动自动开始；到期后保留查看/停止能力 |
| 更新权益 | 1 年 | `updates_until` 之后仍可运行，但不再承诺新版本 |
| 设备数 | 2 台 | 策略字段；离线无法强制统计，以机器绑定 + 先解除后换机执行 |
| 收款 | Merchant of Record | 推荐 Lemon Squeezy / Paddle，处理税务与退款 |
| 激活 | 离线密钥 | 用户粘贴 `PWV1.…`，不联网 |

许可与设备绑定：`license.json` 保存当前机器指纹；把整个数据目录复制到另一台机器
不会生效。换机时先在旧机 `deactivate`，或由卖家重签。

**更新权益在哪里落地**：`panweb update`（命令行与控制台「系统与数据」页同源）。它先读
许可的 `updates_active`，再看 GitHub Release 的版本号——窗口过期就返回 `license_expired`
并说明"已装版本不受影响，可继续用"，续费后同一密钥重新激活即可继续升级。取回的升级包只
落到 `~/.panweb/update/` 并打开挂载窗口，替换 App 那一步由用户自己拖拽：程序不偷偷换掉
正在运行的二进制。所以"1 年更新"是靠**不给升级包**执行的，不是靠让旧版本跑不起来。

## 2. 生成发行密钥

```bash
python3 tools/license_tool.py keygen --out keys
# keys/private.pem   ← 离线保管，绝不提交
# keys/public.pem    ← 内置到发行包
cp keys/public.pem assets/license_public_key.pem
python3 tools/build_ui.py
```

建议：

- 私钥放在密码管理器/离线加密盘；不要放进 CI secrets 之外的仓库变量。
- 公钥可以公开；它只能验证，不能签发。
- 换密钥会让旧许可全部失效，发行后不要更换。
- 为不同产品线（Pro/团队版）生成独立密钥对与公钥文件。

## 3. 签发许可

```bash
python3 tools/license_tool.py issue \
  --private-key keys/private.pem \
  --license-id PW-2026-0001 \
  --buyer alice@example.com \
  --devices 2 \
  --updates-days 365 \
  --out licenses/PW-2026-0001.key
```

输出文件内容就是用户粘贴的密钥（单行 `PWV1.<payload>.<sig>`）。可先把
`--buyer` 换成订单号/邮箱哈希，避免在许可中保存不必要的个人信息。

验证签发结果：

```bash
python3 tools/license_tool.py verify \
  --key licenses/PW-2026-0001.key \
  --public-key keys/public.pem
```

### 支付平台接入

1. 在 Lemon Squeezy / Paddle 创建一次性买断商品（含税价自定）。
2. 开启购买成功 Webhook，把订单号/邮箱写入你的内部队列。
3. 队列消费者调用 `license_tool.py issue` 生成密钥，通过邮件/成功页交付。
4. 退款政策由 Merchant of Record 处理；panweb 不做在线吊销（离线许可没有吊销通道）。
   需要“退款失效”时，只能停止后续更新或以新版本/新公钥重签，属于运营取舍。

## 4. 用户侧

```bash
panweb license status
panweb license activate "PWV1.…"
panweb license deactivate
```

控制台「系统与数据 → 买断许可」提供同样的激活/解除入口；试用到期时顶部显示
激活横幅，发布按钮会引导到激活弹窗。

## 5. 构建变体

| 变体 | 公钥 | 行为 |
| --- | --- | --- |
| 配置缺失 | 无公钥且未显式开关 | `misconfigured`，**拒绝发布**（fail-closed） |
| 源码/开发 | 无公钥 + `PANWEB_LICENSE_OFF=1` | `development`，不限制功能 |
| 试用发行 | 有公钥，无许可 | 首次运行开始 14 天试用 |
| 买断发行 | 有公钥 | 用户激活后长期可用 |
| 内部测试 | `PANWEB_LICENSE_OFF=1` | 强制开发模式（不要用于发行） |

相关环境变量（仅调试/测试）：

- `PANWEB_LICENSE_PUBKEY`：公钥 PEM 或路径，覆盖内置公钥。
- `PANWEB_LICENSE_OFF=1`：显式关闭校验；未设置且无公钥时按配置错误拒绝发布。
- `PANWEB_TRIAL_DAYS=N`：试用天数。
- `PANWEB_MACHINE_ID=...`：覆盖机器指纹（测试用）。

## 6. 隐私与安全

- 不联网校验，不上传机器指纹；`machine_id` 是本地信息的 SHA-256 截断。
- 许可文件权限 600；私钥不进入 App、不进入 Git、不打进 zipapp。
- 离线许可无法阻止有决心的用户修改客户端；买断制的目标是**诚实用户便利 +
  合法用户可迁移**，不是强 DRM。若需要强防破解，需要服务端激活，但这会引入
  账号、隐私与可用性成本，本产品明确不采用。
- 试用状态存在本地 `~/.panweb/license.json`，删除文件可重置试用；这是离线产品的
  已知取舍。发行版可在安装器中写入只读标记降低误删，但不能真正防住。

## 7. 发布前检查清单

- [ ] `assets/license_public_key.pem` 是**发行公钥**，不是测试公钥
- [ ] `keys/private.pem` 不在仓库、不在 App、不在 CI 日志
- [ ] 试用天数/更新权益/设备数与商品页文案一致
- [ ] EULA、隐私说明、退款政策已由所有者确认
- [ ] `python3 tools/build_ui.py --check`
- [ ] `python3 -m unittest discover -s tests -v`
- [ ] `panweb install-app` 后，在干净用户目录测试：试用 → 激活 → 解除 → 再激活
- [ ] 断网测试：激活/状态/发布均不依赖网络（隧道本身需要网络）

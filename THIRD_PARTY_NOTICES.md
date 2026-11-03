# 第三方组件声明

panweb 本体使用 Python 标准库，并在运行时/发布产物中包含以下第三方组件：

## cloudflared

- 项目：Cloudflare Tunnel 客户端（`cloudflared`）
- 版权：Cloudflare, Inc.
- 许可证：Apache License 2.0
- 来源：https://github.com/cloudflare/cloudflared
- 说明：`panweb install-app` 会把本机已安装的 cloudflared 二进制复制进 `.app`。
  分发该 App 时请一并保留 cloudflared 的 LICENSE/NOTICE，并遵守 Apache-2.0。

## QR Code Generator for JavaScript

- 作者：Kazuhiko Arase
- 许可证：MIT License
- 来源：http://www.d-project.com/
- 说明：源码位于 `ui/vendor/qrcode.js`，构建时内联进 `ui/index.html`。
  "QR Code" 是 DENSO WAVE INCORPORATED 的注册商标。

## xterm.js（终端渲染）

- 项目：`@xterm/xterm` 5.5.0、`@xterm/addon-fit` 0.10.0、`@xterm/addon-canvas` 0.7.0
- 版权：The xterm.js authors；早期代码 Copyright (c) 2012-2013, Christopher Jeffrey
- 许可证：MIT License（全文见 `ui/vendor/LICENSE.xterm`、`ui/vendor/LICENSE.addon-fit`、
  `ui/vendor/LICENSE.addon-canvas`）
- 来源：https://github.com/xtermjs/xterm.js
- 说明：控制台「终端」页用它渲染伪终端画面（canvas 渲染器 + 自适应尺寸）。源码位于
  `ui/vendor/xterm.js`、`ui/vendor/xterm.css`、`ui/vendor/addon-fit.js`、
  `ui/vendor/addon-canvas.js`，构建时原样内联进 `ui/index.html`，离线可用；
  除删除指向未随包分发的 `.map` 的 `sourceMappingURL` 注释行外未作改动。

## OpenSSL（仅卖家工具）

- 项目：OpenSSL
- 许可证：Apache License 2.0
- 来源：https://www.openssl.org/
- 说明：`tools/license_tool.py` 调用本机 `openssl` 生成/签发许可密钥。
  OpenSSL 不随 panweb 发行包分发，也不参与运行期许可校验。

## Python 标准库

- 许可证：Python Software Foundation License
- 说明：panweb 仅使用 Python 标准库，不随项目分发 Python 解释器。

---

本仓库自身的许可证尚未声明（默认保留所有权利）。如果计划公开分发，
请由仓库所有者补充 LICENSE 文件。

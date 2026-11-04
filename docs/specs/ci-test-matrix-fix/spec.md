# CI 测试矩阵修复与 macOS 首跑诊断

## 背景

`main` 已普通推送到 `origin/main`（`6c84f65..2a67373`，43 个提交，未推 tag、未 force）。
本次 workflow run `41767036867` 的结果：

| job | 结果 | 失败点 |
| --- | --- | --- |
| lint | 通过 | — |
| test (3.9) | 失败 | `actions/setup-python@v5` 步骤本身失败，测试未开始 |
| test (3.11) | 失败 | Unit & CLI tests：312 项中 3 failures + 2 errors |
| test (3.12) | 失败 | Unit & CLI tests：同一组 3 failures + 2 errors |
| coverage | 失败 | Measure coverage（跑的是同一套测试） |
| macos | 失败 | Unit & CLI tests：312 项中 10 failures，全部是“代理未启动” |

本机（macOS arm64）用 Python 3.9.6 与 3.12.14 跑全量均为 `Ran 312 tests ... OK`，
最小化环境（`env -i`）下代理相关测试也通过，说明 Linux 与 macOS runner 的失败来自
**测试隐含的环境假设**，不是本机可复现的产品缺陷。

### 已定位的 Linux 根因

1. `tests/test_recovery.py` 的 `RecoveryTests` 没有隔离 `supervisor.find_cloudflared()`。
   Ubuntu runner 没有安装 cloudflared，两个恢复用例在进入被测逻辑前就抛
   `dependency_missing: 未找到 cloudflared`（2 errors）。
2. `tests/test_update.py` 的 `ApplyTests._run()` 默认只生成 **arm64** dmg 的
   `SHA256SUMS`，而 `update.pick_asset()` 用真实 `platform.machine()` 选包。
   Ubuntu runner 是 x86_64，选中 `panweb-9.9.9-x86_64.dmg`，摘要清单里没有它，
   于是 3 个用例从预期的 `network` / `not_found` / 成功路径变成 `checksum` 失败。
   本机是 arm64，所以一直通过。

### macOS 尚未定位

macOS job 的 10 个失败全部止于 `port_listening(proxy_port)` 为假（“代理未启动”），
涉及 `test_integration.py`（3）、`test_selfcheck.py`（4）、`test_upstream.py`（3）。
该 job 已 `brew install cloudflared`，且 `test_update.py` 在 macOS 上没有失败，
说明不是 cloudflared 或架构选择问题。当前 CI 日志只有断言行，没有子进程的
`*-proxy.log` 内容，必须先取到子进程日志才能判断是环境假设还是产品缺陷。

## 目标

1. 修正 Linux 上两处真实存在的测试环境假设，**不跳过测试、不削弱断言**。
2. 给 macOS 的“代理未启动”断言补上子进程日志，用一次真实 CI 运行拿到根因。
3. 依据日志修 macOS 的环境/配置假设；若是产品缺陷则停下报告。
4. 让 lint、3.9/3.11/3.12、coverage、macos 六个 job 全部通过。

## 非目标

- 不推 tag、不使用 `--force` / `--force-with-lease`。
- 不把失败测试改成 skip，不放宽断言来换绿灯。
- 不改 P1 六个产品模块（supervisor.py、visits.py、update.py、licensing.py、
  jobs.py、lifecycle.py）的行为；只在测试里隔离它们的外部依赖。
- 未经证据确认，不改产品代码。

## 变更设计

### C1 Linux：恢复测试不再依赖真实 cloudflared

文件：`tests/test_recovery.py`，`RecoveryTests.setUp`。

```python
patcher = mock.patch.object(supervisor, "find_cloudflared",
                            return_value="/usr/local/bin/cloudflared")
patcher.start()
self.addCleanup(patcher.stop)
```

理由：这两个用例本来就已替换 `start_tunnel` / `kill_process`，测试对象是恢复流程，
不是二进制发现。隔离后 Linux 与 macOS 行为一致，且原有断言全部保留。

### C2 Linux：更新测试固定到 fixture 的 arm64 架构

文件：`tests/test_update.py`，`ApplyTests.setUp`。

```python
patcher = mock.patch.object(update.platform, "machine", return_value="arm64")
patcher.start()
self.addCleanup(patcher.stop)
```

理由：`release()` fixture 的 `SHA256SUMS` 按 arm64 命名构造，本组用例的意图是验证
许可窗口、下载、校验、清理，而不是架构选择；架构选择已由 `AssetTests` 用显式
mock 覆盖。固定 fixture 架构既保留全部断言，又让 x86_64 与 arm64 runner 结果一致。
`test_plain_http_asset_is_refused` 在 arm64 下会选中被改成 http 的 `assets[0]`，
仍按原断言得到 `not_found`。

### C3 macOS：把代理子进程日志带进失败信息

文件：`tests/helpers.py` 新增：

```python
def proxy_log_tail(entry_id, limit=1500):
    path = os.path.join(runtime.LOG_DIR, "%s-proxy.log" % entry_id)
    try:
        with open(path, "rb") as f:
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return "（没有代理日志）"
    return (data[-limit:] or "（代理日志为空）")
```

在三个“代理未启动”断言处追加日志（断言条件不变）：

- `tests/test_integration.py` 的三个用例：`"代理未启动\n" + proxy_log_tail(entry_id)`
- `tests/test_selfcheck.py` 的 `publish()`：`"代理未启动\n" + proxy_log_tail(entry_id)`
- `tests/test_upstream.py` 的 `spawn()`：`"代理未启动\n" + proxy_log_tail(entry_id)`

### C4 macOS 根因判定与修复分支（按日志证据选择）

重新推送后查看 macos job 的 “Unit & CLI tests” 日志：

| 日志证据 | 判定 | 动作 |
| --- | --- | --- |
| `No module named panweb` / `PYTHONPATH` / 解释器路径错误 | 测试启动子进程的环境假设 | 在测试侧显式设置子进程可导入路径或改用 `sys.executable -c`；只改测试/ workflow |
| `Address already in use` / 端口相关 traceback | 测试端口选择竞态 | 测试内选择端口/重试策略调整，保留断言 |
| 日志为空，子进程仍存活 | runner 回环访问/防火墙差异 | 在 workflow 测试前关闭 macOS 应用防火墙（`socketfilterfw --setglobalstate off`），并记录理由 |
| 日志显示子进程启动耗时超过 8 秒 | 测试等待窗口过短 | 把三处 `deadline = time.time() + 8` 提高到 20 秒；断言不变 |
| 日志显示真实产品 traceback（与运行环境无关） | 产品缺陷 | **停止**，不修、不推，向用户报告 |

任何分支都必须保留断言强度；不确定时按“停止并报告”处理。

### C5 3.9 setup-python 失败

先重跑失败的 `test (3.9)` job 一次：

- 若成功：判定为 runner 瞬时故障，不做代码改动。
- 若仍失败：读取该步骤 annotation；按错误选择
  `ubuntu-22.04` 作为 3.9 的 runner，或把 `python-version` 固定为可用的 3.9 小版本，
  并在提交信息里写明原因。

## 验收标准

1. 本机 Python 3.9（`/usr/bin/python3`）与 3.12（`~/.local/bin/python3.12`）
   全量均为 `Ran 312 tests ... OK`。
2. `python3 tools/build_ui.py --check` 通过。
3. CI ruff 规则 `ruff check --select E9,F63,F7,F82 src tools tests` 通过。
4. 普通 push 后，run 的六个 job（lint、test 3.9、test 3.11、test 3.12、coverage、macos）
   全部 success；macOS job 说明它实际跑过了代理子进程、App 打包与 dmg 构建。
5. 不推 tag；如遇权限/网络阻塞，如实报告并停止。

## 需要用户确认

允许修改上述测试文件（`tests/helpers.py`、`test_integration.py`、`test_selfcheck.py`、
`test_upstream.py`、`test_recovery.py`、`test_update.py`）以及必要时修改
`.github/workflows/test.yml`，并按 C1–C5 追加提交、再次普通 push、观察 CI。

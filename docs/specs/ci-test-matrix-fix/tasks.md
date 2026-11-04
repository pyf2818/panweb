# 任务清单

- [x] T1 按 C1 隔离 `tests/test_recovery.py` 对真实 cloudflared 的依赖
- [x] T2 按 C2 在 `tests/test_update.py` 的 `ApplyTests.setUp` 固定 `platform.machine=arm64`
- [x] T3 按 C3 在 `tests/helpers.py` 增加 `proxy_log_tail`，并接入三个“代理未启动”断言
- [x] T4 本机验证：Python 3.9 与 3.12 全量 312 项、`build_ui.py --check`、ruff
- [x] T5 只 add 上述测试文件，提交（说明“为什么”），普通 push，不推 tag
- [x] T6 观察新 run；读取 macos 日志中的代理子进程输出，按 C4 判定并修复或停止
- [x] T7 按 C5 处理 `test (3.9)` 的 setup-python 失败（重跑或调整 runner/版本）
- [ ] T8 确认 lint、3.9、3.11、3.12、coverage、macos 全部通过，输出中文汇报

## 汇报必须包含

- 远端分支与推送范围（commit 起点到终点、提交数量）
- 每个 job 的最终结果
- macOS job 首次真实运行的结论：跑过了什么；失败根因是否属于环境假设、改了什么
- 为此追加的提交列表
- 未做/被阻塞的部分

"""真终端后端：白名单 Agent 跑在 PTY 里，键盘进、画面出、尺寸变、退出有码。"""
import os
import tempfile
import time
import unittest
from unittest import mock

from helpers import FAKE_PTY, PtyCase, make_executable, temp_home
from panweb import agents, term
from panweb.errors import PanwebError


class TableTests(unittest.TestCase):
    def test_agent_whitelist_only(self):
        """终端只认识 Agent，不认识 shell：可执行名来自固定白名单。"""
        self.assertEqual(set(agents.TERMINALS), {"claude", "codex", "opencode"})
        for item in agents.TERMINALS.values():
            self.assertTrue(item["argv"], "每家都得带上「允许它动手」的开关")
            self.assertTrue(item["note"], "界面上要写清楚动手意味着什么")

    def test_list_marks_readiness_without_running_anything(self):
        out = agents.core_terminal_agents()
        self.assertEqual(len(out), 3)
        for a in out:
            self.assertIn("ready", a)
            self.assertIn("path", a)


class PtyTests(PtyCase):
    def test_open_gives_a_live_pty_with_interactive_argv(self):
        session = self.open_fake()
        self.assertTrue(session["alive"])
        self.assertEqual(session["cwd"], os.path.realpath(self.bin))
        self.assertEqual((session["cols"], session["rows"]), (90, 24))
        # argv 直接交给交互进程：没有 --print 那种一次性开关，也没有经过 shell
        self.assertIn("ARGV --approve-for-me",
                      self.wait_for(session["id"], "BANNER-TAIL"))

    def test_typed_bytes_echo_back(self):
        sid = self.boot()
        self.type_(sid, "hi")
        self.wait_for(sid, "hi")

    def test_resize_reaches_the_child(self):
        sid = self.boot()
        term.core_terminal_resize(sid, 132, 43)
        self.type_(sid, "size\r")
        self.wait_for(sid, "SIZE 43 132")
        self.assertEqual(term._sessions[sid]["cols"], 132)

    def test_size_defaults_and_clamps(self):
        self.assertEqual(term._size(0, 0), (100, 30))
        self.assertEqual(term._size("x", None), (100, 30))
        self.assertEqual(term._size(99999, 3), (term.MAX_COLS, term.MIN_ROWS))
        summary = term.core_terminal_resize(self.boot(), 0, 99999)
        self.assertEqual((summary["cols"], summary["rows"]), (100, 200))

    def test_exit_codes_reach_the_surface(self):
        sid = self.boot()
        self.type_(sid, "exit\r")
        self.assertEqual(self.wait_dead(sid)["exit_code"], 0)
        other = self.boot()
        self.type_(other, "crash\r")
        self.assertEqual(self.wait_dead(other)["exit_code"], 3)

    def test_input_rejects_bad_base64_and_huge_blobs(self):
        sid = self.boot()
        with self.assertRaises(PanwebError) as bad:
            term.core_terminal_input(sid, "!!!不是 base64!!!")
        self.assertEqual(bad.exception.err_type, "invalid_argument")
        with self.assertRaises(PanwebError) as wrong:
            term.core_terminal_input(sid, {"data": "aGk="})
        self.assertEqual(wrong.exception.err_type, "invalid_argument")
        with self.assertRaises(PanwebError) as big:
            self.type_(sid, "x" * (term.MAX_INPUT + 1))
        self.assertEqual(big.exception.err_type, "too_large")

    def test_big_paste_writes_without_hanging(self):
        """主端非阻塞：粘满上限也该写得完，不会把请求线程钉在内核里。"""
        sid = self.boot()
        self.type_(sid, "z" * (term.MAX_INPUT - 8))
        self.wait_for(sid, "zzzzz")

    def test_buffer_is_capped(self):
        with mock.patch.object(term, "MAX_BUFFER", 20000):
            sid = self.boot()
            self.type_(sid, "spam\r")
            self.wait_for(sid, "AAAA")
            deadline = time.time() + 15
            while time.time() < deadline and term._sessions[sid]["start"] == 0:
                time.sleep(0.05)
            session = term._sessions[sid]
            with session["cond"]:
                self.assertLessEqual(len(session["buf"]), 20000)
                self.assertGreater(session["start"], 0)
                self.assertGreater(session["end"], 20000)

    def test_write_after_exit_is_refused(self):
        sid = self.boot()
        self.type_(sid, "exit\r")
        self.wait_dead(sid)
        with self.assertRaises(PanwebError) as refused:
            self.type_(sid, "again")
        self.assertEqual(refused.exception.err_type, "exited")

    def test_close_kills_the_child_and_forgets_the_session(self):
        sid = self.boot()
        proc = term._sessions[sid]["proc"]
        self.addCleanup(proc.wait)
        self.assertTrue(term.core_terminal_close(sid)["closed"])
        self.assertEqual(term.core_terminal_sessions(), [])
        with self.assertRaises(PanwebError) as gone:
            self.type_(sid, "hi")
        self.assertEqual(gone.exception.err_type, "not_found")

    def test_close_releases_the_master_fd(self):
        sid = self.boot()
        session = term._sessions[sid]      # 关掉后会话就从注册表里没了，先拿住引用
        master = session["master"]
        term.core_terminal_close(sid)
        deadline = time.time() + 10
        while time.time() < deadline and session["master"] is not None:
            time.sleep(0.05)
        self.assertIsNone(session["master"], "读线程没关主端")
        with self.assertRaises(OSError):     # fd 真的还给了系统
            os.fstat(master)

    def test_concurrency_cap_leaves_live_terminals_alone(self):
        with mock.patch.object(term, "MAX_TERMS", 1):
            first = self.boot()
            with self.assertRaises(PanwebError) as busy:
                self.open_fake()
            self.assertEqual(busy.exception.err_type, "busy")
            self.assertTrue(term._sessions[first]["alive"], "满员不该偷偷杀旧的")

    def test_dead_sessions_get_pruned(self):
        first = self.boot()
        self.type_(first, "exit\r")
        self.wait_dead(first)
        second = self.boot()
        self.type_(second, "exit\r")
        self.wait_dead(second)
        third = self.boot()       # 再开一个时，最早退出的那个被收掉
        ids = [s["id"] for s in term.core_terminal_sessions()]
        self.assertNotIn(first, ids)
        self.assertIn(third, ids)

    def test_close_all_terminates_agents_and_refuses_late_opens(self):
        self.boot()
        self.boot()
        procs = [s["proc"] for s in term._sessions.values()]
        term.close_all_terms()
        self.assertEqual(term.core_terminal_sessions(), [])
        for proc in procs:
            self.assertIsNotNone(proc.poll(), "控制台退出了，Agent 还在跑")
        with self.assertRaises(PanwebError) as late:
            self.open_fake()
        self.assertEqual(late.exception.err_type, "busy")

    def test_rejects_unknown_agent_and_bad_folder(self):
        with self.assertRaises(PanwebError) as nope:
            term.core_terminal_open("sh", cwd=self.bin)
        self.assertEqual(nope.exception.err_type, "not_found")
        with self.assertRaises(PanwebError) as missing:
            term.core_terminal_open("missing", cwd=self.bin)
        self.assertEqual(missing.exception.err_type, "dependency_missing")
        with self.assertRaises(PanwebError) as bad:
            term.core_terminal_open("fake", cwd="/definitely/not/here")
        self.assertEqual(bad.exception.err_type, "invalid_argument")

    def test_failed_launch_leaves_no_session_behind(self):
        """起进程失败时，注册表与 fd 都不许留下。"""
        with mock.patch.object(term.subprocess, "Popen",
                               side_effect=OSError("没门")):
            with self.assertRaises(PanwebError) as e:
                self.open_fake()
        self.assertEqual(e.exception.err_type, "launch_failed")
        self.assertEqual(term.core_terminal_sessions(), [])


class EnvTests(unittest.TestCase):
    def test_child_env_sets_term_and_appends_path(self):
        with temp_home("panweb-term-env-"):
            base = os.environ.get("PATH", "")
            with tempfile.TemporaryDirectory() as bindir:
                env = term._child_env("/tmp", os.path.join(bindir, "fake"),
                                      "abc123")
                self.assertIn(bindir, env["PATH"].split(os.pathsep))
            self.assertEqual(env["TERM"], "xterm-256color")
            self.assertEqual(env["PWD"], "/tmp")
            self.assertEqual(env["PANWEB_TERM"], "abc123")
            # 兜底目录只能追加：前置会让 ~/bin 里的同名二进制劫持 Agent 的命令
            self.assertTrue(env["PATH"].startswith(base))

    def test_find_binary_falls_back_to_common_install_dirs(self):
        """从启动台打开的 App 里 PATH 很短：常见安装目录要能兜住。"""
        with tempfile.TemporaryDirectory() as tmp:
            make_executable(tmp, "panweb-fake-pty-agent", FAKE_PTY)
            with mock.patch.object(agents.runtime, "USER_BIN_DIRS", [tmp]):
                self.assertEqual(
                    agents.find_agent_binary("panweb-fake-pty-agent"),
                    os.path.join(tmp, "panweb-fake-pty-agent"))
                self.assertIsNone(agents.find_agent_binary("definitely-not-here"))


if __name__ == "__main__":
    unittest.main()

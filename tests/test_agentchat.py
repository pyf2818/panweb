"""终端页的会话后端：只跑白名单里的本机 Agent，argv 不经 shell，输出能收回来。"""
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock

from helpers import temp_home
from panweb import agentchat
from panweb.errors import PanwebError

FAKE = """#!/usr/bin/env python3
import json, os, sys, time
argv = sys.argv[1:]
print(json.dumps({"argv": argv, "cwd": os.getcwd()}, ensure_ascii=False), flush=True)
joined = " ".join(argv)
if "SLOW" in joined:
    for i in range(30):
        print("tick %d" % i, flush=True)
        time.sleep(1)
elif "LEAK" in joined:
    # 真实 Agent 会在退出前留下继承同一根管道的后台钩子
    if os.fork() == 0:
        time.sleep(25)
        os._exit(0)
    print("正文已经打完了", flush=True)
    sys.exit(0)
else:
    print("已发布：https://fake.trycloudflare.com", flush=True)
"""


class RunnerTable(unittest.TestCase):
    def test_known_agents_only(self):
        self.assertEqual(set(agentchat.RUNNERS), {"claude", "codex", "opencode"})
        for runner in agentchat.RUNNERS.values():
            self.assertTrue(runner["argv"], "每家都得带上「允许它动手」的开关")
            self.assertTrue(runner["note"], "界面上要写清楚动手意味着什么")

    def test_list_marks_readiness_without_running_anything(self):
        out = agentchat.core_agent_list()
        self.assertEqual(len(out), 3)
        for a in out:
            self.assertIn("ready", a)


class SessionTests(unittest.TestCase):
    """假 Agent 只回显自己的 argv，所以能同时验证命令行、工作目录和输出回收。"""

    def setUp(self):
        self.ctx = temp_home("panweb-agent-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self.bin = tempfile.mkdtemp(prefix="panweb-fakebin-")
        self.addCleanup(shutil.rmtree, self.bin, True)
        path = os.path.join(self.bin, "fake-agent")
        with open(path, "w", encoding="utf-8") as f:
            f.write(FAKE)
        os.chmod(path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP |
                 stat.S_IROTH | stat.S_IXOTH)
        self._path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.bin + os.pathsep + self._path
        self.addCleanup(os.environ.__setitem__, "PATH", self._path)
        runners = {
            "fake": {"bin": "fake-agent", "name": "Fake Agent",
                     "argv": ("--print", "--dangerously-skip-permissions"),
                     "note": "测试用"},
            "fakecodex": {"bin": "fake-agent", "name": "Fake Codex",
                          "argv": ("exec", "--approve-for-me"), "dash": True,
                          "note": "测试用"},
            "missing": {"bin": "definitely-not-installed", "name": "Missing",
                        "argv": ("--print",), "note": "测试用"},
        }
        patcher = mock.patch.dict(agentchat.RUNNERS, runners, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.reset()
        self.addCleanup(self.reset)

    def reset(self):
        for session in list(agentchat._sessions.values()):
            agentchat._kill(session["proc"])
        agentchat._sessions.clear()
        del agentchat._order[:]

    def wait(self, sid, want, timeout=12.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            done = agentchat.core_agent_output(sid)
            if done["status"] in want:
                return done
            time.sleep(0.15)
        self.fail("会话状态没变成 %s：%s" % (want, agentchat.core_agent_sessions()))

    def argv_of(self, done):
        """输出会跨轮累积，取最后一条回显才知道这一轮发了什么。"""
        lines = [ln for ln in done["text"].splitlines() if ln.startswith("{")]
        self.assertTrue(lines, "假 Agent 没有回显 argv：%r" % done["text"][:200])
        return json.loads(lines[-1])

    def test_start_runs_the_agent_and_collects_output(self):
        sid = agentchat.core_agent_start("fake", cwd=self.bin,
                                         text="把 3000 端口发出去")["id"]
        done = self.wait(sid, {"idle", "failed"})
        self.assertEqual(done["status"], "idle", done.get("error"))
        self.assertIn("已发布", done["text"])
        sent = self.argv_of(done)
        self.assertEqual(sent["cwd"], os.path.realpath(self.bin))
        self.assertIn("--dangerously-skip-permissions", sent["argv"])
        self.assertIn("把 3000 端口发出去", " ".join(sent["argv"]))

    def test_prompt_carries_the_safety_rules(self):
        sid = agentchat.core_agent_start("fake", cwd=self.bin, text="随便发一个")["id"]
        joined = " ".join(self.argv_of(self.wait(sid, {"idle", "failed"}))["argv"])
        self.assertIn("高危", joined, "高危目标要先说风险")
        self.assertIn("secrets", joined, "不该让它去翻口令文件")

    def test_codex_style_gets_a_double_dash(self):
        sid = agentchat.core_agent_start("fakecodex", cwd=self.bin,
                                         text="-rm 开头也要安全")["id"]
        argv = self.argv_of(self.wait(sid, {"idle", "failed"}))["argv"]
        self.assertEqual(argv[-2], "--", "以短横开头的正文不能被当成开关")

    def test_second_turn_carries_the_history(self):
        sid = agentchat.core_agent_start("fake", cwd=self.bin, text="第一条")["id"]
        self.wait(sid, {"idle"})
        agentchat.core_agent_send(sid, "第二条")
        joined = " ".join(self.argv_of(self.wait(sid, {"idle"}))["argv"])
        self.assertIn("第一条", joined)
        self.assertIn("第二条", joined)
        self.assertGreaterEqual(agentchat.core_agent_sessions()[0]["turns"], 2)

    def test_unknown_agent_and_missing_binary_are_refused(self):
        with self.assertRaises(PanwebError) as bad:
            agentchat.core_agent_start("nope", cwd=self.bin, text="hi")
        self.assertEqual(bad.exception.err_type, "not_found")
        with self.assertRaises(PanwebError) as miss:
            agentchat.core_agent_start("missing", cwd=self.bin, text="hi")
        self.assertEqual(miss.exception.err_type, "dependency_missing")

    def test_cwd_must_exist(self):
        with self.assertRaises(PanwebError) as bad:
            agentchat.core_agent_start("fake", cwd="/definitely/not/here", text="hi")
        self.assertEqual(bad.exception.err_type, "invalid_argument")

    def test_empty_turn_is_refused(self):
        sid = agentchat.core_agent_start("fake", cwd=self.bin, text="先起个会话")["id"]
        self.wait(sid, {"idle"})
        with self.assertRaises(PanwebError) as bad:
            agentchat.core_agent_send(sid, "   ")
        self.assertEqual(bad.exception.err_type, "invalid_argument")

    def test_a_detached_hook_cannot_hold_the_turn_open(self):
        """Agent 留下继承管道的后台钩子很常见——不能因此永远停在"正在思考"。"""
        sid = agentchat.core_agent_start("fake", cwd=self.bin,
                                        text="LEAK 打完就走")["id"]
        started = time.time()
        done = self.wait(sid, {"idle"}, 15.0)
        self.assertLess(time.time() - started, 12.0, "收工太慢，界面会一直转圈")
        self.assertIn("正文已经打完了", done["text"])

    def test_stop_kills_a_running_turn_and_keeps_the_verdict(self):
        sid = agentchat.core_agent_start("fake", cwd=self.bin,
                                         text="SLOW 慢慢来")["id"]
        self.wait(sid, {"running"}, 6.0)
        self.assertEqual(agentchat.core_agent_stop(sid)["status"], "stopped")
        done = self.wait(sid, {"stopped"}, 8.0)
        self.assertEqual(done["status"], "stopped", "线程收尾时不该把状态盖成空闲")

    def test_concurrency_is_capped(self):
        first = agentchat.core_agent_start("fake", cwd=self.bin, text="SLOW a")["id"]
        second = agentchat.core_agent_start("fake", cwd=self.bin, text="SLOW b")["id"]
        self.wait(first, {"running"}, 6.0)
        self.wait(second, {"running"}, 6.0)
        with self.assertRaises(PanwebError) as busy:
            agentchat.core_agent_start("fake", cwd=self.bin, text="第三个")
        self.assertEqual(busy.exception.err_type, "busy")

    def test_output_cursor_only_returns_the_new_part(self):
        sid = agentchat.core_agent_start("fake", cwd=self.bin, text="看这里")["id"]
        done = self.wait(sid, {"idle"})
        again = agentchat.core_agent_output(sid, done["after"])
        self.assertEqual(again["text"], "")
        self.assertEqual(again["after"], done["after"])

    def test_long_output_is_trimmed_from_the_head(self):
        session = {"out": "", "lock": threading.Lock()}
        with mock.patch.object(agentchat, "MAX_OUTPUT", 100):
            agentchat._append_output(session, "x" * 60)
            agentchat._append_output(session, "y" * 60)
        self.assertEqual(len(session["out"]), 100)
        self.assertTrue(session["out"].startswith("x"), "该丢的是最早的部分")

    def test_a_finished_session_takes_the_next_turn(self):
        sid = agentchat.core_agent_start("fake", cwd=self.bin, text="第一轮")["id"]
        self.wait(sid, {"idle"})
        agentchat.core_agent_send(sid, "第二轮")
        self.wait(sid, {"running"}, 3.0)
        done = self.wait(sid, {"idle"})
        self.assertGreaterEqual(done["turns"], 4, "两问两答都记在会话里")
        self.assertGreater(done["after"], 0)


if __name__ == "__main__":
    unittest.main()

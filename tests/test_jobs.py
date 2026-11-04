"""后台任务：步骤、结果和错误都要能从轮询里看到，不能悄悄丢掉。"""
import threading
import time
import unittest
from unittest import mock

from helpers import temp_home  # noqa: F401  顺带把 src/ 放进 sys.path
from panweb import jobs
from panweb.errors import PanwebError


class JobTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-jobs-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self._reset()
        self.addCleanup(self._reset)

    def _reset(self):
        with jobs._LOCK:
            jobs._JOBS.clear()
            jobs._FLIGHT.clear()

    def _wait(self, job_id, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = jobs.get(job_id)
            if state and state["done"]:
                return state
            time.sleep(0.01)
        self.fail("任务在 %.1f 秒内没有结束" % timeout)

    def test_progress_seen_while_running(self):
        gate = threading.Event()

        def work(progress):
            progress("第一步")
            gate.wait(2)
            progress("第二步")
            return {"value": 7}

        job_id = jobs.start("demo", work)
        deadline = time.time() + 2
        while time.time() < deadline:
            state = jobs.get(job_id)
            if state and state["steps"] == ["第一步"]:
                break
            time.sleep(0.01)
        else:
            self.fail("运行中拿不到步骤")
        gate.set()
        state = self._wait(job_id)
        self.assertTrue(state["ok"])
        self.assertEqual(state["result"], {"value": 7})
        self.assertEqual(state["steps"], ["第一步", "第二步"])

    def test_error_keeps_hint(self):
        def work(progress):
            raise PanwebError(8, "port_not_serving", "端口没人听", "先启动应用")

        state = self._wait(jobs.start("demo", work))
        self.assertFalse(state["ok"])
        self.assertEqual(state["error"]["type"], "port_not_serving")
        self.assertEqual(state["error"]["hint"], "先启动应用")

    def test_unknown_job_is_none(self):
        self.assertIsNone(jobs.get("nope"))

    def test_repeated_step_is_not_duplicated(self):
        def work(progress):
            progress("同一步")
            progress("同一步")
            return True

        state = self._wait(jobs.start("demo", work))
        self.assertEqual(state["steps"], ["同一步"])

    def test_running_jobs_are_never_evicted(self):
        gate = threading.Event()

        def slow(progress):
            gate.wait(2)
            return True

        with mock.patch.object(jobs, "MAX_JOBS", 2):
            ids = [jobs.start("slow", slow, key=str(i)) for i in range(4)]
        try:
            for job_id in ids:
                self.assertIsNotNone(jobs.get(job_id), "运行中的任务不能被淘汰")
        finally:
            gate.set()
        for job_id in ids:
            self._wait(job_id)

    def test_terminal_jobs_are_evicted_first(self):
        with mock.patch.object(jobs, "MAX_JOBS", 2):
            ids = []
            for i in range(4):
                ids.append(jobs.start("quick", lambda p: True, key=str(i)))
                self._wait(ids[-1])
        self.assertEqual(len(jobs._JOBS), 2)
        self.assertIsNone(jobs.get(ids[0]))
        self.assertIsNotNone(jobs.get(ids[-1]))

    def test_same_kind_target_is_single_flight(self):
        gate = threading.Event()
        calls = []

        def work(progress):
            calls.append(1)
            gate.wait(2)
            return True

        first = jobs.start("publish", work, key=3000)
        again = jobs.start("publish", work, key="3000")
        other = jobs.start("publish", work, key=4000)
        self.assertEqual(first, again, "同目标重复提交应复用运行中的 job")
        self.assertNotEqual(first, other)
        gate.set()
        for job_id in (first, other):
            self._wait(job_id)
        self.assertEqual(len(calls), 2, "复用请求不能再执行一遍")
        retry = jobs.start("publish", lambda p: True, key=3000)
        self.assertNotEqual(retry, first, "终态后重试应创建新任务")
        self._wait(retry)


if __name__ == "__main__":
    unittest.main()

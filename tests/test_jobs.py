"""后台任务：步骤、结果和错误都要能从轮询里看到，不能悄悄丢掉。"""
import threading
import time
import unittest

from helpers import temp_home  # noqa: F401  顺带把 src/ 放进 sys.path
from panweb import jobs
from panweb.errors import PanwebError


class JobTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-jobs-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)

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


if __name__ == "__main__":
    unittest.main()

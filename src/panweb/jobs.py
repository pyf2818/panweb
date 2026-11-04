"""后台任务：发布/启动这类慢动作放到线程里跑，前端按 job id 轮询进度。

状态只活在本进程内；控制台重启后旧 job 消失，前端会拿到 not_found，
这比把半截状态写进 ``~/.panweb`` 更干净。
"""
import threading
import time
import uuid

from .errors import PanwebError

MAX_JOBS = 20
_JOBS = {}
_FLIGHT = {}
_LOCK = threading.RLock()


def _evict_locked():
    """只淘汰终态任务；全在跑宁可暂时超限，也不能把轮询中的 job 弄丢。"""
    overflow = len(_JOBS) - MAX_JOBS
    if overflow <= 0:
        return
    for job_id in list(_JOBS):
        if overflow <= 0:
            break
        if _JOBS[job_id]["done"]:
            _JOBS.pop(job_id, None)
            overflow -= 1


def start(kind, fn, key=None):
    """跑 ``fn(progress)``，返回 job id；异常收敛成错误 JSON，不吞掉。

    传入 ``key``（如端口/目录）时对同 kind/target 做 single-flight：
    运行中的重复请求直接复用同一个 job，避免同一应用被并发发布两次。
    """
    single = (kind, str(key)) if key is not None else None
    with _LOCK:
        if single:
            existing = _JOBS.get(_FLIGHT.get(single))
            if existing and not existing["done"]:
                return existing["id"]
        job_id = uuid.uuid4().hex[:8]
        state = {"id": job_id, "kind": kind, "step": "准备中…", "steps": [],
                 "done": False, "ok": None, "result": None, "error": None,
                 "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "elapsed": 0.0}
        _JOBS[job_id] = state
        if single:
            _FLIGHT[single] = job_id
        _evict_locked()

    def progress(message):
        with _LOCK:
            state["step"] = message
            if not state["steps"] or state["steps"][-1] != message:
                state["steps"].append(message)

    def run():
        began = time.time()
        try:
            result = fn(progress)
        except PanwebError as e:
            with _LOCK:
                state.update(ok=False, error=e.to_dict()["error"])
        except Exception as e:  # noqa: BLE001  后台线程不能把异常漏给解释器
            with _LOCK:
                state.update(ok=False, error={
                    "type": "internal_error", "message": str(e)})
        else:
            with _LOCK:
                state.update(ok=True, result=result)
        finally:
            with _LOCK:
                state.update(done=True, elapsed=round(time.time() - began, 1),
                             step="完成")
                if single and _FLIGHT.get(single) == job_id:
                    _FLIGHT.pop(single, None)

    threading.Thread(target=run, daemon=True,
                     name="panweb-job-%s" % job_id).start()
    return job_id


def get(job_id):
    """拿一份快照，避免调用方直接改内部状态。"""
    with _LOCK:
        state = _JOBS.get(job_id)
        if not state:
            return None
        return dict(state, steps=list(state["steps"]))

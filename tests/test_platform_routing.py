import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webui.runner as runner_module


class FakeAccountStore:
    def __init__(self, accounts):
        self.accounts = accounts

    def list(self):
        return [dict(account) for account in self.accounts]

    def mark_quota_exhausted(self, _account_id):
        raise AssertionError("测试账号不应耗尽额度")


class FakeTaskStore:
    def __init__(self, task=None):
        self.task = task

    def get(self, _task_id):
        if self.task is None:
            raise KeyError("测试任务不存在")
        return dict(self.task)


class FakeRuntimeStore:
    def write(self, state):
        self.last_state = state


class FakePlatformSettingsStore:
    def __init__(self, platforms):
        self.platforms = platforms

    def get(self):
        return {"enabled_platforms": list(self.platforms)}


class PlatformRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_generators = dict(runner_module.VIDEO_GENERATORS)
        self.calls = []
        calls = self.calls

        class FakeDoubaoGenerator:
            def __init__(self, account_file):
                self.account_file = account_file

            async def main(self, **kwargs):
                calls.append(("doubao", self.account_file))
                await asyncio.sleep(0.01)
                return Path(kwargs["save_dir"]) / "doubao-test.mp4"

        class FakeDolaGenerator:
            def __init__(self, account_file):
                self.account_file = account_file

            async def main(self, **kwargs):
                calls.append(("dola", self.account_file))
                await asyncio.sleep(0.01)
                return Path(kwargs["save_dir"]) / "dola-test.mp4"

        runner_module.VIDEO_GENERATORS.update(
            {"doubao": FakeDoubaoGenerator, "dola": FakeDolaGenerator}
        )

    async def asyncTearDown(self):
        runner_module.VIDEO_GENERATORS.clear()
        runner_module.VIDEO_GENERATORS.update(self.original_generators)

    async def run_platforms(self, platforms, count):
        accounts = [
            {
                "id": "doubao-id",
                "name": "豆包测试",
                "platform": "doubao",
                "enabled": True,
                "cookie_exists": True,
                "quota_exhausted_today": False,
                "cookie_path": "doubao-cookie.json",
            },
            {
                "id": "dola-id",
                "name": "Dola测试",
                "platform": "dola",
                "enabled": True,
                "cookie_exists": True,
                "quota_exhausted_today": False,
                "cookie_path": "dola-cookie.json",
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            task_runner = runner_module.TaskRunner(
                FakeAccountStore(accounts),
                FakeTaskStore(),
                FakeRuntimeStore(),
                FakePlatformSettingsStore(platforms),
            )
            state = {"status": "starting"}
            request = {
                "run_id": "test-run",
                "source": "test",
                "requested_at": "2026-09-09T00:00:00+08:00",
                "is_direct": True,
                "direct_state": state,
                "task_snapshot": {
                    "id": "test-task",
                    "name": "测试任务",
                    "count": count,
                    "prompt": "测试提示词",
                    "images": [],
                    "ratio": "9:16",
                    "output_dir": temp_dir,
                    "theme": "test",
                    "headless": True,
                    "enable_blur": False,
                    "max_retries": 0,
                    "model": "Seedance 2.0 Fast",
                },
            }
            await task_runner._execute(request)
            return state

    async def test_dola_only_uses_dola_account_and_generator(self):
        state = await self.run_platforms(["dola"], count=1)
        self.assertEqual([platform for platform, _ in self.calls], ["dola"])
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["jobs"][0]["platform"], "dola")

    async def test_both_platforms_run_concurrently(self):
        state = await self.run_platforms(["doubao", "dola"], count=2)
        self.assertEqual({platform for platform, _ in self.calls}, {"doubao", "dola"})
        self.assertEqual(state["completed_count"], 2)

    async def test_immediate_run_enters_front_of_unified_queue(self):
        accounts = [
            {
                "id": "dola-id",
                "name": "Dola测试",
                "platform": "dola",
                "enabled": True,
                "cookie_exists": True,
                "quota_exhausted_today": False,
                "cookie_path": "dola-cookie.json",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            task = {
                "id": "direct-task",
                "name": "立即执行测试",
                "count": 1,
                "prompt": "测试提示词",
                "images": [],
                "ratio": "9:16",
                "output_dir": temp_dir,
                "theme": "test",
                "headless": True,
                "enable_blur": False,
                "max_retries": 0,
                "model": "Seedance 2.0 Fast",
            }
            task_runner = runner_module.TaskRunner(
                FakeAccountStore(accounts),
                FakeTaskStore(task),
                FakeRuntimeStore(),
                FakePlatformSettingsStore(["dola"]),
            )
            normal = await task_runner.enqueue(task["id"])
            created = await task_runner.run_direct(task["id"])
            snapshot = task_runner.snapshot()
            self.assertTrue(snapshot["queue_running"])
            self.assertFalse(snapshot["direct_active"])
            self.assertEqual(snapshot["queue_runs"][0]["run_id"], created["run_id"])
            self.assertEqual(snapshot["queue_runs"][0]["source"], "immediate")
            self.assertTrue(snapshot["queue_runs"][0]["priority"])
            self.assertEqual(snapshot["queue_runs"][0]["status"], "queued")
            self.assertEqual(task_runner.pending[0]["run_id"], created["run_id"])
            self.assertEqual(task_runner.pending[1]["run_id"], normal["run_id"])

            task_runner.orchestrator_task = asyncio.create_task(
                task_runner._orchestrator()
            )
            try:
                for _ in range(100):
                    if task_runner.run_states[created["run_id"]]["status"] == "completed":
                        break
                    await asyncio.sleep(0.01)
                else:
                    self.fail("立即运行任务没有在测试时间内完成")

                self.assertFalse(task_runner.queue_running)
                self.assertIsNone(task_runner.single_run_id)
                self.assertEqual(
                    task_runner.run_states[normal["run_id"]]["status"], "queued"
                )
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(task_runner.pending[0]["run_id"], normal["run_id"])
            finally:
                task_runner.stopping = True
                task_runner.orchestrator_task.cancel()
                await asyncio.gather(
                    task_runner.orchestrator_task, return_exceptions=True
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from webui.runtime_log import SessionLogStore, bind_log_context


class SessionLogStoreTests(unittest.TestCase):
    def test_snapshot_returns_only_entries_after_cursor(self) -> None:
        store = SessionLogStore(max_entries=10)
        first = store.add("第一条")
        second = store.add("第二条", level="WARNING")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        snapshot = store.snapshot(after_id=first["id"])

        self.assertEqual([entry["message"] for entry in snapshot["entries"]], ["第二条"])
        self.assertEqual(snapshot["latest_id"], second["id"])

    def test_context_is_attached_to_captured_entries(self) -> None:
        store = SessionLogStore(max_entries=10)
        with bind_log_context(task_name="测试任务", job="1/2", account_name="账号1"):
            entry = store.add("步骤1完成")

        self.assertEqual(entry["task_name"], "测试任务")
        self.assertEqual(entry["job"], "1/2")
        self.assertEqual(entry["account_name"], "账号1")
        self.assertEqual(entry["level"], "SUCCESS")

    def test_ring_buffer_keeps_latest_entries(self) -> None:
        store = SessionLogStore(max_entries=2)
        store.add("第一条")
        store.add("第二条")
        store.add("第三条")

        self.assertEqual(
            [entry["message"] for entry in store.snapshot()["entries"]],
            ["第二条", "第三条"],
        )


if __name__ == "__main__":
    unittest.main()

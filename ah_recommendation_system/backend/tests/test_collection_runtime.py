import threading
import time
import unittest


class TestCollectionRuntime(unittest.TestCase):
    def test_timeout_returns_without_starting_duplicate_pending_task(self):
        from ah_recommendation_system.backend.stock_recommend.collection_runtime import CollectionRuntime

        gate = threading.Event()
        calls = []
        runtime = CollectionRuntime(max_workers=1)

        def slow():
            calls.append(1)
            gate.wait(1)
            return {"ok": True}

        first = runtime.run({"events": (slow, 0.01)})["events"]
        second = runtime.run({"events": (slow, 0.01)})["events"]
        gate.set()
        self.assertEqual(first.status, "timeout_pending")
        self.assertEqual(second.status, "timeout_pending")
        self.assertEqual(len(calls), 1)

    def test_capacity_exhaustion_is_reported_without_unbounded_workers(self):
        from ah_recommendation_system.backend.stock_recommend.collection_runtime import CollectionRuntime

        gate = threading.Event()
        runtime = CollectionRuntime(max_workers=1)
        try:
            first = runtime.run({"a": (lambda: gate.wait(1), 0.01)})["a"]
            second = runtime.run({"b": (lambda: True, 0.01)})["b"]
            self.assertEqual(first.status, "timeout_pending")
            self.assertEqual(second.status, "capacity_exhausted")
        finally:
            gate.set()

    def test_reclaim_returns_late_success_without_starting_a_new_call(self):
        from ah_recommendation_system.backend.stock_recommend.collection_runtime import CollectionRuntime

        gate = threading.Event()
        calls = []
        runtime = CollectionRuntime(max_workers=1)

        def slow():
            calls.append(1)
            gate.wait(1)
            return {"rows": [1, 2, 3]}

        first = runtime.run({"fundamental": (slow, 0.01)})["fundamental"]
        self.assertEqual(first.status, "timeout_pending")
        gate.set()
        late = runtime.reclaim("fundamental", extra_wait_seconds=0.5)
        self.assertEqual(late.status, "ok")
        self.assertEqual(late.value, {"rows": [1, 2, 3]})
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

import threading
import unittest
from gisheh.jobs import BackgroundJobs


class JobTests(unittest.TestCase):
    def setUp(self):
        self.callbacks = []
        self.jobs = BackgroundJobs(
            lambda fn, *args: self.callbacks.append(lambda: fn(*args)),
            workers=1,
            image_workers=1,
        )
        self.addCleanup(self.jobs.close)

    def test_delivery_after_close_or_session_change_is_discarded(self):
        values = []
        self.jobs.submit("a", lambda: self.jobs.post(values.append, 1)).result(2)
        self.jobs.invalidate()
        self.callbacks.pop()()
        self.assertEqual(values, [])
        self.jobs.submit("b", lambda: self.jobs.post(values.append, 2)).result(2)
        self.jobs.close()
        self.callbacks.pop()()
        self.assertEqual(values, [])

    def test_running_request_remembers_old_session(self):
        started, proceed = threading.Event(), threading.Event()
        values = []

        def work():
            started.set()
            proceed.wait(2)
            self.jobs.post(values.append, "old")

        task = self.jobs.submit("a", work)
        self.assertTrue(started.wait(2))
        self.jobs.invalidate()
        proceed.set()
        task.result(2)
        self.callbacks.pop()()
        self.assertEqual(values, [])

    def test_image_workers_inherit_session(self):
        values = []

        def work():
            with self.jobs.image_executor() as executor:
                executor.submit(self.jobs.post, values.append, 1).result(2)

        self.jobs.submit("a", work).result(2)
        self.jobs.invalidate()
        self.callbacks.pop()()
        self.assertEqual(values, [])

    def test_invalidation_cancels_queued_jobs_without_mutating_iteration(self):
        started, proceed = threading.Event(), threading.Event()

        def running():
            started.set()
            proceed.wait(2)

        first = self.jobs.submit("running", running)
        self.assertTrue(started.wait(2))
        pending = [self.jobs.submit(str(i), lambda: None) for i in range(10)]
        self.jobs.invalidate()
        proceed.set()
        first.result(2)
        self.assertTrue(all(task.cancelled() for task in pending))

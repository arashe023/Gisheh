"""Bounded background execution with session-scoped delivery and shutdown."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
import threading
from functools import wraps

_EPOCH = ContextVar("gisheh_job_epoch", default=None)


class ContextExecutor:
    def __init__(self, executor):
        self.executor = executor

    def submit(self, function, *args, **kwargs):
        return self.executor.submit(copy_context().run, function, *args, **kwargs)


class BackgroundJobs:
    def __init__(self, dispatch, *, workers=4, image_workers=8):
        self.dispatch = dispatch
        self.executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="gisheh-job"
        )
        self.images = ThreadPoolExecutor(
            max_workers=image_workers, thread_name_prefix="gisheh-image"
        )
        self.lock = threading.RLock()
        self.pending = {}
        self.epoch = 0
        self.closed = False

    def submit(self, name, function, *args):
        with self.lock:
            if self.closed:
                return None
            epoch = self.epoch

            def run():
                if self.closed or epoch != self.epoch:
                    return
                token = _EPOCH.set(epoch)
                try:
                    return function(*args)
                finally:
                    _EPOCH.reset(token)

            future = self.executor.submit(run)
            self.pending[future] = future
            future.add_done_callback(self._completed)
            return future

    def _completed(self, future):
        with self.lock:
            self.pending.pop(future, None)
        if not future.cancelled() and future.exception() is not None:
            import logging

            logging.getLogger("io.github.arashe023.Gisheh").error(
                "Background job failed", exc_info=future.exception()
            )

    def post(self, callback, *args):
        epoch = _EPOCH.get()
        if epoch is None:
            epoch = self.epoch

        @wraps(callback)
        def deliver(*arguments):
            if self.closed or epoch != self.epoch:
                return False
            return callback(*arguments)

        return self.dispatch(deliver, *args)

    @contextmanager
    def image_executor(self):
        yield ContextExecutor(self.images)

    def invalidate(self):
        with self.lock:
            self.epoch += 1
            for future in tuple(self.pending.values()):
                future.cancel()
            self.pending.clear()

    def close(self):
        with self.lock:
            self.closed = True
            self.invalidate()
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.images.shutdown(wait=False, cancel_futures=True)

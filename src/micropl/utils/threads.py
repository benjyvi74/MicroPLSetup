"""
Threading utilities for PyQt6 applications.
"""

import logging
from typing import Callable, Any, Optional
from PyQt6.QtCore import QThread, QObject, pyqtSignal

logger = logging.getLogger(__name__)


class Worker(QObject):
    """
    Generic worker for running tasks in a QThread.

    Signals:
        started: Emitted when task starts
        finished: Emitted when task completes successfully with result
        error: Emitted when task raises an exception with (exception, traceback)
        progress: Emitted to report progress (current, total, message)
    """

    started = pyqtSignal()
    finished = pyqtSignal(object)  # result
    error = pyqtSignal(Exception, str)  # exception, traceback
    progress = pyqtSignal(int, int, str)  # current, total, message

    def __init__(self, func: Callable, *args, **kwargs):
        """
        Initialize worker.

        Args:
            func: Function to run in thread
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
        """
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self._is_running = False

    def run(self):
        """Execute the worker function."""
        try:
            self._is_running = True
            self.started.emit()

            logger.debug(f"Worker starting: {self.func.__name__}")

            result = self.func(*self.args, **self.kwargs)

            self.finished.emit(result)
            logger.debug(f"Worker finished: {self.func.__name__}")

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"Worker error in {self.func.__name__}: {e}\n{tb}")
            self.error.emit(e, tb)

        finally:
            self._is_running = False

    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._is_running

    def report_progress(self, current: int, total: int, message: str = ""):
        """
        Report progress from within worker function.

        Args:
            current: Current step number
            total: Total number of steps
            message: Optional progress message
        """
        self.progress.emit(current, total, message)


class WorkerThread(QThread):
    """
    Thread for running a worker.

    This is a convenience class that manages the QThread lifecycle.
    """

    def __init__(self, worker: Worker):
        super().__init__()
        self.worker = worker
        self.worker.moveToThread(self)

    def run(self):
        """Run the worker."""
        self.worker.run()


def run_in_thread(func: Callable,
                 on_finished: Optional[Callable] = None,
                 on_error: Optional[Callable] = None,
                 on_progress: Optional[Callable] = None,
                 *args, **kwargs) -> WorkerThread:
    """
    Convenience function to run a function in a thread.

    Args:
        func: Function to run
        on_finished: Callback for completion (receives result)
        on_error: Callback for errors (receives exception, traceback)
        on_progress: Callback for progress (receives current, total, message)
        *args: Arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        WorkerThread instance (already started)

    Example:
        def long_task(x):
            # Do something
            return x * 2

        def on_done(result):
            print(f"Result: {result}")

        thread = run_in_thread(long_task, on_done, x=42)
    """
    worker = Worker(func, *args, **kwargs)

    if on_finished:
        worker.finished.connect(on_finished)

    if on_error:
        worker.error.connect(on_error)

    if on_progress:
        worker.progress.connect(on_progress)

    thread = WorkerThread(worker)
    thread.start()

    return thread


class ProgressWorker(Worker):
    """
    Worker with built-in progress tracking.

    Subclass this and implement do_work() to use.
    """

    def __init__(self, *args, **kwargs):
        def wrapper():
            return self.do_work()

        super().__init__(wrapper, *args, **kwargs)

    def do_work(self) -> Any:
        """
        Override this method to implement the actual work.

        Use self.update_progress(current, total, message) to report progress.
        """
        raise NotImplementedError("Subclass must implement do_work()")

    def update_progress(self, current: int, total: int, message: str = ""):
        """
        Report progress.

        Args:
            current: Current step
            total: Total steps
            message: Optional message
        """
        self.progress.emit(current, total, message)


class CancellableWorker(Worker):
    """
    Worker that can be cancelled.

    Check self.is_cancelled() periodically in your work function.
    """

    cancelled = pyqtSignal()

    def __init__(self, func: Callable, *args, **kwargs):
        super().__init__(func, *args, **kwargs)
        self._is_cancelled = False

    def cancel(self):
        """Request cancellation of the worker."""
        logger.info("Worker cancellation requested")
        self._is_cancelled = True
        self.cancelled.emit()

    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._is_cancelled

    def run(self):
        """Execute with cancellation support."""
        try:
            self._is_running = True
            self.started.emit()

            if self._is_cancelled:
                logger.info("Worker cancelled before start")
                return

            result = self.func(*self.args, **self.kwargs)

            if not self._is_cancelled:
                self.finished.emit(result)
            else:
                logger.info("Worker was cancelled")

        except Exception as e:
            if not self._is_cancelled:
                import traceback
                tb = traceback.format_exc()
                logger.error(f"Worker error: {e}\n{tb}")
                self.error.emit(e, tb)

        finally:
            self._is_running = False

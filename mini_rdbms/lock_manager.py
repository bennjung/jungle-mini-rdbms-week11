"""Table-scoped reader/writer locking primitives."""

import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager


class RWLock:
    """A writer-preferred reader/writer lock."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @contextmanager
    def read_lock(self) -> Iterator[None]:
        """Acquire a shared read lock."""
        with self._cond:
            while self._writer or self._waiting_writers > 0:
                self._cond.wait()
            self._readers += 1

        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @contextmanager
    def write_lock(self) -> Iterator[None]:
        """Acquire an exclusive write lock."""
        with self._cond:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers > 0:
                    self._cond.wait()
            finally:
                self._waiting_writers -= 1
            self._writer = True

        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()


class TableLockManager:
    """Manage pre-created reader/writer locks for known tables."""

    def __init__(self, table_names: Iterable[str]) -> None:
        self._locks = {table_name: RWLock() for table_name in table_names}

    @contextmanager
    def read_lock(self, table_name: str) -> Iterator[None]:
        """Acquire a read lock when the table is known."""
        lock = self._locks.get(table_name)
        if lock is None:
            yield
            return

        with lock.read_lock():
            yield

    @contextmanager
    def write_lock(self, table_name: str) -> Iterator[None]:
        """Acquire a write lock when the table is known."""
        lock = self._locks.get(table_name)
        if lock is None:
            yield
            return

        with lock.write_lock():
            yield

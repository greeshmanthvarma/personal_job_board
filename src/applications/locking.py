"""Prevent concurrent discovery runs from overwriting local state."""
import fcntl
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def execution_lock(data: Path):
    data.mkdir(parents=True, exist_ok=True)
    with (data/'execution.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as err:
            raise RuntimeError('Another polling command is active.') from err
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

"""Durable atomic JSON replacements and coordinated snapshot seam."""
import fcntl
import json
import os
import tempfile
from functools import wraps
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def snapshot_lock(data: Path):
    data.mkdir(parents=True, exist_ok=True)
    with (data/'snapshot.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.'+path.name+'.',delete=False) as handle:
            name=handle.name
            os.chmod(name,0o600)
            json.dump(value,handle,ensure_ascii=False)
            handle.flush();os.fsync(handle.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if name and os.path.exists(name):os.unlink(name)

def locked_data(function):
    @wraps(function)
    def wrapped(data, *args, **kwargs):
        with snapshot_lock(data):
            return function(data, *args, **kwargs)
    return wrapped

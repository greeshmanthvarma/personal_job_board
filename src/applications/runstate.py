"""Small local run-status sidecar, not a background scheduler."""
import json
import os
from pathlib import Path
from applications.schedule import stamp, utc_now
from applications.storage import atomic_json, snapshot_lock


def save_run(path: Path, run: dict) -> None:
    run['updated_at'] = stamp(utc_now())
    path.parent.mkdir(parents=True, exist_ok=True)
    with snapshot_lock(path.parent):
        atomic_json(path, run)


def load_run(path: Path) -> dict:
    if not path.exists():
        return {'status': 'unknown', 'message': 'No saved run status. Start a scan to record progress.'}
    run = json.loads(path.read_text(encoding='utf-8'))
    if run.get('status') == 'running':
        try:
            os.kill(int(run['pid']), 0)
        except (ProcessLookupError, KeyError, ValueError):
            run['status'] = 'interrupted'
            run['message'] = 'The recorded process is no longer running.'
        except PermissionError:
            pass
    return run

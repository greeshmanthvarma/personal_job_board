"""Board poll schedule. A board is never deleted because a request failed."""

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from applications.storage import atomic_json, snapshot_lock

SIX_HOURS = timedelta(hours=6)
ONE_HOUR = timedelta(hours=1)
ONE_DAY = timedelta(days=1)
ONE_WEEK = timedelta(days=7)


@dataclass
class BoardState:
    next_check: str = ""
    consecutive_failures: int = 0
    lever_host: str = ""
    last_status: str = ""
    open_jobs: int | None = None
    hiring_engineers: bool = False


def load_schedule(path: Path) -> dict[str, BoardState]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: BoardState(
            next_check=value.get("next_check") or "",
            consecutive_failures=int(value.get("consecutive_failures") or 0),
            lever_host=value.get("lever_host") or "",
            last_status=value.get("last_status") or "",
            open_jobs=value.get("open_jobs"),
            hiring_engineers=bool(value.get("hiring_engineers", False)),
        )
        for key, value in raw.items()
    }


def save_schedule(path: Path, states: dict[str, BoardState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: asdict(state) for key, state in states.items()}
    with snapshot_lock(path.parent):
        atomic_json(path, payload)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_due(state: BoardState | None, now: datetime) -> bool:
    if state is None or not state.next_check:
        return True
    return state.next_check <= stamp(now)

def select_due(boards, states, now, limit=None, backlog=False):
    due = [board for board in boards if backlog or is_due(states.get(board.key), now)]
    due.sort(key=lambda board: states.get(board.key, BoardState()).next_check)
    if limit is None:
        return due
    if limit < 1:
        return []
    hiring = [b for b in due if states.get(b.key, BoardState()).hiring_engineers]
    broad = [b for b in due if not states.get(b.key, BoardState()).hiring_engineers]
    # Reserve half for broader discovery, then borrow unused slots.
    selected = broad[:(limit+1)//2] + hiring[:limit//2]
    used = {b.key for b in selected}
    selected += [b for b in due if b.key not in used][:limit-len(selected)]
    return selected


def advance(state: BoardState | None, *, ok: bool, job_count: int, now: datetime, status: str, hiring_engineers: bool = False) -> BoardState:
    current = state or BoardState()
    if not ok:
        failures = current.consecutive_failures + 1
        interval = ONE_WEEK if failures >= 3 else SIX_HOURS
        return replace(
            current,
            next_check=stamp(now + interval),
            consecutive_failures=failures,
            last_status=status,
        )
    hiring = bool(hiring_engineers) and job_count > 0
    interval = ONE_DAY if job_count == 0 else ONE_HOUR if hiring else SIX_HOURS
    return replace(
        current,
        next_check=stamp(now + interval),
        consecutive_failures=0,
        last_status=status,
        open_jobs=job_count,
        hiring_engineers=hiring,
    )

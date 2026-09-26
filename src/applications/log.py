"""CSV log and draft sidecar. Dedup is on portal plus external id."""

import csv
import json
from pathlib import Path

from applications.models import COLUMNS, Record


class ApplicationLog:
    def __init__(self, path: Path):
        self.path = path
        self.rows = load_records(path)
        self.latest = {f"{row.portal}\t{row.external_job_id}": row.stage for row in self.rows}

    def contains(self, portal: str, external_job_id: str) -> bool:
        return self.latest.get(f"{portal}\t{external_job_id}") in {"keyword_reject", "eligibility_reject", "jev_no", "drafted", "submitted"}

    def retryable(self, portal: str, external_job_id: str) -> bool:
        return self.latest.get(f"{portal}\t{external_job_id}") in {"failed", "blocked", "jev_yes"}

    def append(self, record: Record) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if new_file:
                writer.writerow(COLUMNS)
            writer.writerow(record.as_row())
        self.rows.append(record)
        self.latest[f"{record.portal}\t{record.external_job_id}"] = record.stage


def load_records(path: Path) -> list[Record]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            Record(
                timestamp=row.get("timestamp") or "",
                portal=row.get("portal") or "",
                external_job_id=row.get("external_job_id") or "",
                job=row.get("job") or "",
                company=row.get("company") or "",
                link=row.get("link") or "",
                stage=row.get("stage") or "",
                reason=row.get("reason") or "",
                model=row.get("model") or "",
            )
            for row in reader
        ]


def latest_by_job(rows: list[Record]) -> list[Record]:
    order: list[str] = []
    latest: dict[str, Record] = {}
    for row in rows:
        key = f"{row.portal}\t{row.external_job_id}"
        if key not in latest:
            order.append(key)
        latest[key] = row
    return [latest[key] for key in order]


def load_drafts(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_draft(path: Path, key: str, draft: dict) -> None:
    data = load_drafts(path)
    data[key] = draft
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

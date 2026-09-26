"""CSV log and draft sidecar. Dedup is on portal plus external id."""

import csv
import json
from pathlib import Path
from urllib.parse import urlparse, unquote

from applications.models import COLUMNS, Record
from applications.identity import canonical_id


class ApplicationLog:
    def __init__(self, path: Path, *, recheck_location: bool = False, backlog: bool = False):
        self.path = path
        self.rows = load_records(path)
        self.latest = {f"{row.portal}\t{row.external_job_id}": row.stage for row in self.rows}
        latest_rows = {f"{row.portal}\t{row.external_job_id}": row for row in self.rows}
        self.age_rechecks = {
            key for key, row in latest_rows.items()
            if backlog and row.stage == 'keyword_reject'
            and (row.reason.startswith('posted more than 24 hours ago') or row.reason == 'posted date missing')
        }
        self.location_rechecks = {
            key: row for key, row in latest_rows.items()
            if recheck_location and row.stage == 'jev_no' and not row.model
            and row.reason.startswith(('uncertain: location', 'uncertain: remote'))
        }

    def recheck_board(self, board) -> bool:
        return any(row.portal == board.vendor == 'ashby' and
                   unquote(urlparse(row.link).path).strip('/').split('/')[0].casefold() == board.slug.casefold()
                   for row in self.location_rechecks.values())

    def contains(self, portal: str, external_job_id: str) -> bool:
        if f"{portal}\t{external_job_id}" in self.location_rechecks or f"{portal}\t{external_job_id}" in self.age_rechecks:
            return False
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
        self.location_rechecks.pop(f"{record.portal}\t{record.external_job_id}", None)
        self.age_rechecks.discard(f"{record.portal}\t{record.external_job_id}")


def load_records(path: Path) -> list[Record]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            Record(
                timestamp=row.get("timestamp") or "",
                portal=row.get("portal") or "",
                external_job_id=canonical_id(row.get('portal') or '', row.get("external_job_id") or ""),
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
    values = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for key, draft in values.items():
        portal, separator, job_id = key.partition('\t')
        result[f'{portal}\t{canonical_id(portal, job_id)}' if separator else key] = draft
    return result


def save_draft(path: Path, key: str, draft: dict) -> None:
    data = load_drafts(path)
    data[key] = draft
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

"""Public board reads. One company board per request."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

from applications.models import Board, JobPosting, Question
from applications.textutil import strip_html
from applications.identity import canonical_id


class BoardError(Exception):
    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class BoardFetch:
    ok: bool
    status: str
    jobs: tuple[JobPosting, ...]
    lever_host: str
    error: str = ""


def fetch_board(board: Board, get, lever_host: str = "") -> BoardFetch:
    try:
        if board.vendor == "greenhouse":
            status, payload = _json(get, f"https://boards-api.greenhouse.io/v1/boards/{quote(board.slug)}/jobs")
            return BoardFetch(True, str(status), tuple(parse_greenhouse_jobs(payload, board)), "")
        if board.vendor == "ashby":
            status, payload = _json(get, f"https://api.ashbyhq.com/posting-api/job-board/{quote(board.slug)}")
            return BoardFetch(True, str(status), tuple(parse_ashby_jobs(payload, board)), "")
        if board.vendor == "lever":
            return _fetch_lever(board, get, lever_host)
    except BoardError as err:
        return BoardFetch(False, str(err.status or "error"), (), lever_host, err.message)
    return BoardFetch(False, "error", (), lever_host, f"unknown vendor {board.vendor}")


def fetch_greenhouse_job(board: Board, job_id: str, get) -> JobPosting:
    status, payload = _json(get, f"https://boards-api.greenhouse.io/v1/boards/{quote(board.slug)}/jobs/{quote(job_id)}")
    jobs = parse_greenhouse_jobs({"jobs": [payload]}, board)
    if not jobs:
        raise BoardError(status, "greenhouse job response was empty")
    return jobs[0]


def fetch_greenhouse_questions(board: Board, job_id: str, get) -> list[Question]:
    _status, payload = _json(
        get,
        f"https://boards-api.greenhouse.io/v1/boards/{quote(board.slug)}/jobs/{quote(job_id)}?questions=true",
    )
    return parse_greenhouse_questions(payload)


def parse_greenhouse_jobs(payload: dict, board: Board) -> list[JobPosting]:
    jobs = []
    for item in payload.get("jobs") or []:
        location = item.get("location") or {}
        name = location.get("name") if isinstance(location, dict) else str(location or "")
        jobs.append(
            JobPosting(
                portal="greenhouse",
                external_job_id=str(item.get("id") or ""),
                title=item.get("title") or "",
                company=item.get("company_name") or board.display_name,
                location=name or "",
                link=item.get("absolute_url") or "",
                description_text=strip_html(item.get("content") or ""),
                board_slug=board.slug,
                apply_url=item.get("absolute_url") or "",
                posted_at=parse_posted_at(item.get("first_published")),
            )
        )
    return jobs


def parse_greenhouse_questions(payload: dict) -> list[Question]:
    questions: list[Question] = []
    for key in ("questions", "demographic_questions", "eeoc_questions"):
        for item in payload.get(key) or []:
            fields = item.get("fields") or []
            options: list[str] = []
            kind = "text"
            for field in fields:
                if field.get("type") in {"input_file", "file"}:
                    kind = "file"
                for value in field.get("values") or []:
                    if isinstance(value, dict):
                        options.append(str(value.get("label") or value.get("value") or ""))
                    else:
                        options.append(str(value))
            questions.append(
                Question(
                    label=item.get("label") or "",
                    required=bool(item.get("required")),
                    options=tuple(option for option in options if option),
                    kind=kind,
                )
            )
    return questions


def parse_ashby_jobs(payload: dict | list, board: Board) -> list[JobPosting]:
    items = payload.get("jobs") if isinstance(payload, dict) else payload
    jobs = []
    for item in items or []:
        description = item.get("descriptionPlain") or strip_html(item.get("descriptionHtml") or "")
        job_url = item.get("jobUrl") or ""
        jobs.append(
            JobPosting(
                portal="ashby",
                external_job_id=canonical_id('ashby', job_url),
                title=item.get("title") or "",
                company=board.display_name,
                location=_ashby_location(item),
                link=job_url or item.get("applyUrl") or "",
                description_text=description,
                board_slug=board.slug,
                is_listed=bool(item.get("isListed", True)),
                apply_url=item.get("applyUrl") or "",
                posted_at=parse_posted_at(item.get("publishedAt")),
            )
        )
    return jobs


def _ashby_location(item: dict) -> str:
    """Prefer a documented US location, including a US secondary location."""
    locations = [item, *(item.get('secondaryLocations') or [])]
    known = []
    for entry in locations:
        postal = (entry.get('address') or {}).get('postalAddress') or {}
        country = str(postal.get('addressCountry') or '').strip()
        if country:
            label = entry.get('location') or postal.get('addressLocality') or ''
            known.append((label, country))
            if country.lower() in {'us', 'usa', 'united states', 'united states of america'}:
                return f'{label} [country: {country}]'
    if known:
        label, country = known[0]
        return f'{label} [country: {country}]'
    return item.get('location') or ''


def parse_lever_jobs(payload: dict | list, board: Board) -> list[JobPosting]:
    items = payload
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("postings") or []
    jobs = []
    for item in items or []:
        extra = []
        for block in item.get("lists") or []:
            extra.append(block.get("text") or "")
            extra.append(strip_html(block.get("content") or ""))
        description = item.get("descriptionPlain") or strip_html(item.get("description") or "")
        if any(extra):
            description = f"{description}\n" + "\n".join(part for part in extra if part)
        categories = item.get("categories") or {}
        location = categories.get("location") or ""
        workplace = item.get("workplaceType") or ""
        if workplace and workplace.lower() not in location.lower():
            location = f"{location} {workplace}".strip()
        jobs.append(
            JobPosting(
                portal="lever",
                external_job_id=str(item.get("id") or ""),
                title=item.get("text") or "",
                company=board.display_name,
                location=location,
                link=item.get("hostedUrl") or item.get("applyUrl") or "",
                description_text=description,
                board_slug=board.slug,
                apply_url=item.get("applyUrl") or "",
                posted_at=parse_posted_at(item.get("createdAt")),
            )
        )
    return jobs


def parse_posted_at(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if abs(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return parse_posted_at(int(text))
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def questions_from_html(page: str) -> list[Question]:
    import re

    labels = re.findall(r"<label[^>]*>(.*?)</label>", page or "", flags=re.IGNORECASE | re.DOTALL)
    questions = []
    for raw in labels:
        label = strip_html(raw)
        if not label:
            continue
        required = "*" in raw or "required" in raw.lower()
        questions.append(Question(label=label.replace("*", "").strip(), required=required))
    return questions


def _fetch_lever(board: Board, get, lever_host: str) -> BoardFetch:
    hosts = [lever_host] if lever_host else ["https://api.lever.co", "https://api.eu.lever.co"]
    last_error = "lever request failed"
    for host in hosts:
        jobs: list[JobPosting] = []
        skip = 0
        try:
            while True:
                status, payload = _json(
                    get,
                    f"{host}/v0/postings/{quote(board.slug)}?mode=json&limit=100&skip={skip}",
                )
                page = parse_lever_jobs(payload, board)
                jobs.extend(page)
                if len(page) < 100:
                    return BoardFetch(True, str(status), tuple(jobs), host)
                skip += 100
        except BoardError as err:
            last_error = err.message
            if err.status == 404 and host != hosts[-1]:
                continue
            return BoardFetch(False, str(err.status or "error"), (), "", err.message)
    return BoardFetch(False, "error", (), "", last_error)


def _json(get, url: str) -> tuple[int, dict | list]:
    status, body = get(url)
    if status == 404:
        raise BoardError(404, f"404 for {url}")
    if status != 200:
        raise BoardError(status, f"{status} for {url}")
    try:
        return status, json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as err:
        raise BoardError(status, f"invalid JSON for {url}") from err

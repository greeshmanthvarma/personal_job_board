"""Turn one posting into log rows. This build never writes submitted."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from applications.answers import Draft
from applications.eligibility import eligibility_reason
from applications.keywords import location_decision, title_decision
from applications.models import JobPosting, Record


class StopRun(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Keys:
    typesafe: str
    openai: str
    answer_model: str

    @property
    def ready(self) -> bool:
        return bool(self.typesafe and self.openai)

    @property
    def missing(self) -> str:
        names = []
        if not self.typesafe:
            names.append("TYPESAFE_API_KEY")
        if not self.openai:
            names.append("OPENAI_API_KEY")
        return " and ".join(names)


def keyword_stage(job: JobPosting, now: datetime | None = None, *, retry: bool = False) -> tuple[str, str] | None:
    if not job.is_listed:
        return "keyword_reject", "unlisted Ashby posting (isListed false)"
    title = title_decision(job.title)
    if not title.ok:
        return "keyword_reject", title.reason
    location = location_decision(job.location)
    if location.action == "reject":
        return "keyword_reject", location.reason
    if location.action == "uncertain":
        return "jev_no", f"uncertain: {location.reason}"
    posted = None if retry else posted_within_24_hours(job.posted_at, now or datetime.now(timezone.utc))
    if posted:
        return "keyword_reject", posted
    return None


def posted_within_24_hours(posted_at: datetime | None, now: datetime) -> str | None:
    if posted_at is None:
        return "posted date missing"
    moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    posted = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
    age = moment - posted
    if age < timedelta(hours=24):
        return None
    stamp = posted.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"posted more than 24 hours ago ({stamp})"


def consider(
    job: JobPosting,
    *,
    seen: bool,
    profile: str,
    keys: Keys,
    timestamp: str,
    jev: Callable[[JobPosting], tuple[str, str, str]],
    questions_for: Callable[[JobPosting], list],
    drafter: Callable[[JobPosting, list], Draft],
    retry: bool = False,
) -> list[Record]:
    if seen or not job.external_job_id:
        return []
    keyword = keyword_stage(job, now=_parse_stamp(timestamp), retry=retry)
    if keyword:
        return [_record(job, timestamp, keyword[0], keyword[1])]
    if not (job.description_text or "").strip():
        return [_record(job, timestamp, "failed", "empty description")]
    reason = eligibility_reason(job.description_text)
    if reason:
        return [_record(job, timestamp, "eligibility_reject", reason)]
    if not profile.strip():
        raise StopRun("profile.md is missing")
    if not keys.ready:
        raise StopRun(f"{keys.missing} is missing. Stopping before jev. This job was not logged.")
    stage, jev_reason, model = jev(job)
    if stage != "jev_yes":
        return [_record(job, timestamp, stage, jev_reason, model)]
    questions = questions_for(job)
    yes = _record(job, timestamp, "jev_yes", jev_reason, model)
    if not questions:
        blocked = _record(job, timestamp, "blocked", "could not read application questions")
        return [yes, blocked]
    draft = drafter(job, questions)
    return [yes, _record(job, timestamp, draft.stage, draft.reason, model)]


def _parse_stamp(timestamp: str) -> datetime:
    parsed = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    return parsed.replace(tzinfo=timezone.utc)


def draft_payload(draft: Draft) -> dict:
    return {
        "stage": draft.stage,
        "reason": draft.reason,
        "fields": [
            {"label": field.label, "required": field.required, "kind": field.kind, "answer": field.answer, "reason": field.reason}
            for field in draft.fields
        ],
    }


def _record(job: JobPosting, timestamp: str, stage: str, reason: str, model: str = "") -> Record:
    if stage == "submitted":
        raise RuntimeError("this build does not submit")
    return Record(
        timestamp=timestamp,
        portal=job.portal,
        external_job_id=job.external_job_id,
        job=job.title,
        company=job.company,
        link=job.link,
        stage=stage,
        reason=reason,
        model=model,
    )

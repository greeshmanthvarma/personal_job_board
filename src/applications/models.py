"""Records the poll writes. Stage names and columns come from the spec."""

from dataclasses import dataclass
from datetime import datetime

COLUMNS = (
    "timestamp",
    "portal",
    "external_job_id",
    "job",
    "company",
    "link",
    "stage",
    "reason",
    "model",
)

STAGES = (
    "polled",
    "keyword_reject",
    "eligibility_reject",
    "jev_no",
    "jev_yes",
    "drafted",
    "submitted",
    "failed",
    "blocked",
)


@dataclass(frozen=True)
class Board:
    vendor: str
    company_name: str
    slug: str
    source: str = ""
    source_date: str = ""
    confirmed: str = ""
    http_status: str = ""

    @property
    def key(self) -> str:
        return f"{self.vendor}:{self.slug.casefold()}"

    @property
    def display_name(self) -> str:
        return self.company_name or self.slug


@dataclass
class JobPosting:
    portal: str
    external_job_id: str
    title: str
    company: str
    location: str
    link: str
    description_text: str = ""
    board_slug: str = ""
    is_listed: bool = True
    apply_url: str = ""
    posted_at: datetime | None = None

    @property
    def identity(self) -> str:
        return f"{self.portal}\t{self.external_job_id}"


@dataclass(frozen=True)
class Question:
    label: str
    required: bool
    options: tuple[str, ...] = ()
    kind: str = "text"


@dataclass(frozen=True)
class Record:
    timestamp: str
    portal: str
    external_job_id: str
    job: str
    company: str
    link: str
    stage: str
    reason: str
    model: str = ""

    def as_row(self) -> list[str]:
        return [
            self.timestamp,
            self.portal,
            self.external_job_id,
            self.job,
            self.company,
            self.link,
            self.stage,
            self.reason,
            self.model,
        ]

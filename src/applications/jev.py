"""Jev fit decision. The code writes the reason. The model returns probabilities."""

import json
from dataclasses import dataclass

from applications.models import JobPosting
from applications.textutil import trim_posting

JEV_MODEL = "jev-1.13.0"
YES_AT = 0.8
NO_AT = 0.2
ENDPOINT = "https://api.typesafe.ai/v1/systemone"

JEV_CHECKS = (
    ("role_family", "Is this a software/AI engineering opportunity aligned with the target role families?"),
    ("level", "Does it accept this candidate's level and relevant experience, including stated substitutions?"),
    (
        "responsibilities",
        "Do its core responsibilities plausibly match demonstrated full-stack, backend, agent, retrieval, or infrastructure work?",
    ),
    (
        "qualifications",
        "Are required qualifications supported or explicitly flexible, with no unresolved hard incompatibility?",
    ),
)


class JevError(Exception):
    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class JevDecision:
    stage: str
    reason: str
    model: str


def judge(scores: dict[str, float]) -> JevDecision:
    parts = []
    any_no = False
    any_uncertain = False
    for key, _question in JEV_CHECKS:
        score = scores[key]
        if score >= YES_AT:
            label = "yes"
        elif score <= NO_AT:
            label = "no"
            any_no = True
        else:
            label = "uncertain"
            any_uncertain = True
        parts.append(f"{key} {label} ({score:.2f})")
    detail = "; ".join(parts)
    if not any_no and not any_uncertain:
        return JevDecision("jev_yes", f"yes: {detail}", "")
    if any_no:
        return JevDecision("jev_no", f"no: {detail}", "")
    return JevDecision("jev_no", f"uncertain: {detail}", "")


def request_body(profile: str, job: JobPosting) -> dict:
    return {
        "model": JEV_MODEL,
        "state": {
            "profile": profile,
            "title": job.title,
            "location": job.location,
            "body": trim_posting(job.description_text),
        },
        "questions": {
            key: {
                "type": "noul",
                "instructions": question,
                "criteria": {
                    "true": "The profile and the posting support a clear yes. Do not calculate years or invent citizenship, salary, or sponsorship policy.",
                    "false": "The posting conflicts with the profile, or the role is outside the target families. Accenture network security is not AI or SWE experience.",
                },
            }
            for key, question in JEV_CHECKS
        },
    }


def evaluate(post, api_key: str, profile: str, job: JobPosting, sleep) -> JevDecision:
    if not api_key:
        raise JevError(None, "TYPESAFE_API_KEY is missing")
    payload = request_body(profile, job)
    headers = {"Authorization": f"Bearer {api_key}"}
    status = 0
    body = b""
    for attempt in range(4):
        status, body = post(ENDPOINT, payload, headers)
        if status in {429, 529} and attempt < 3:
            sleep(2 ** (attempt + 1))
            continue
        break
    if status in {401, 422, 429, 529}:
        raise JevError(status, f"jev returned {status}")
    if status != 200:
        raise JevError(status, f"jev returned {status}")
    try:
        parsed = json.loads(body.decode("utf-8"))
        answers = parsed["answers"]
        scores = {key: float(answers[key]["noul"]) for key, _question in JEV_CHECKS}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as err:
        raise JevError(status, "jev response did not include every noul") from err
    decision = judge(scores)
    return JevDecision(decision.stage, decision.reason, parsed.get("model") or JEV_MODEL)

"""Command line. Poll boards, or rebuild the HTML page."""

import argparse
import os
import time
from pathlib import Path

from applications.answers import Draft, draft_answers, model_prompt, needs_model, parse_model_answers
from applications.browser import fetch_rendered_questions
from applications.directory import load_boards
from applications.http import NetworkError, get_bytes, paced_get, post_json, production_limiter
from applications.jev import JevError, evaluate
from applications.log import ApplicationLog, save_draft
from applications.models import Record
from applications.page import render_page
from applications.pipeline import Keys, StopRun, consider, draft_payload, keyword_stage
from applications.portals import BoardError, fetch_board, fetch_greenhouse_job, fetch_greenhouse_questions, questions_from_html
from applications.schedule import BoardState, advance, is_due, load_schedule, save_schedule, stamp, utc_now


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="applications")
    sub = parser.add_subparsers(dest="command", required=True)
    poll = sub.add_parser("poll", help="Poll due boards through drafts")
    poll.add_argument("--limit", type=int)
    poll.add_argument("--vendor", choices=("greenhouse", "ashby", "lever"))
    poll.add_argument("--data-dir", type=Path)
    page = sub.add_parser("page", help="Regenerate data/applications.html")
    page.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)
    root = repo_root()
    load_env(root / ".env")
    data = args.data_dir or (root / "data")
    if args.command == "page":
        render_page(data / "applications.csv", data / "applications.html", data / "drafts.json")
        print(data / "applications.html")
        return 0
    return poll_boards(root, data, limit=args.limit, vendor=args.vendor)


def poll_boards(root: Path, data: Path, limit: int | None, vendor: str | None) -> int:
    boards = load_boards(data / "ats-board-directory.csv")
    if vendor:
        boards = [board for board in boards if board.vendor == vendor]
    states = load_schedule(data / "board-schedule.json")
    now = utc_now()
    due = [board for board in boards if is_due(states.get(board.key), now)]
    if limit is not None:
        due = due[:limit]
    log = ApplicationLog(data / "applications.csv")
    keys = Keys(
        typesafe=os.environ.get("TYPESAFE_API_KEY", "").strip(),
        openai=os.environ.get("OPENAI_API_KEY", "").strip(),
        answer_model=os.environ.get("ANSWER_MODEL", "").strip() or "gpt-6-luna",
    )
    profile_path = root / "profile.md"
    profile = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    getter = paced_get(get_bytes, production_limiter())
    held = False
    message = ""
    for board in due:
        if held:
            break
        state = states.get(board.key)
        try:
            fetched = fetch_board(board, getter, state.lever_host if state else "")
        except NetworkError as err:
            fetched_ok = False
            fetched_status = "timeout"
            fetched_jobs = ()
            fetched_host = state.lever_host if state else ""
            print(f"{board.vendor}:{board.slug} request failed: {err}")
        else:
            fetched_ok = fetched.ok
            fetched_status = fetched.status
            fetched_jobs = fetched.jobs
            fetched_host = fetched.lever_host or (state.lever_host if state else "")
            print(f"{board.vendor}:{board.slug} {fetched.status} jobs={len(fetched.jobs)} {fetched.error}".rstrip())
        if not fetched_ok:
            updated = advance(state, ok=False, job_count=0, now=utc_now(), status=fetched_status)
            updated.lever_host = fetched_host
            states[board.key] = updated
            save_schedule(data / "board-schedule.json", states)
            continue
        for job in fetched_jobs:
            if log.contains(job.portal, job.external_job_id):
                continue
            try:
                job = _hydrate(board, job, getter)
                records_and_draft = _consider_one(job, log, profile, keys, getter, board)
            except BoardError as err:
                log.append(
                    Record(
                        timestamp=stamp(utc_now()),
                        portal=job.portal,
                        external_job_id=job.external_job_id,
                        job=job.title,
                        company=job.company,
                        link=job.link,
                        stage="failed",
                        reason=err.message,
                    )
                )
                continue
            except (StopRun, JevError, NetworkError) as err:
                held = True
                message = getattr(err, "message", str(err))
                break
            records, draft = records_and_draft
            if draft is not None and records:
                save_draft(data / "drafts.json", job.identity, draft)
            for record in records:
                log.append(record)
        if held:
            held_state = states.get(board.key) or BoardState()
            held_state.next_check = stamp(utc_now())
            held_state.lever_host = fetched_host
            states[board.key] = held_state
        else:
            updated = advance(state, ok=True, job_count=len(fetched_jobs), now=utc_now(), status=fetched_status)
            updated.lever_host = fetched_host
            states[board.key] = updated
        save_schedule(data / "board-schedule.json", states)
        render_page(data / "applications.csv", data / "applications.html", data / "drafts.json")
    render_page(data / "applications.csv", data / "applications.html", data / "drafts.json")
    if held:
        print(message)
        return 2
    print(f"polled {len(due)} boards")
    return 0


def _hydrate(board, job, getter):
    if job.portal != "greenhouse" or (job.description_text or "").strip():
        return job
    if keyword_stage(job, retry=True):
        return job
    detailed = fetch_greenhouse_job(board, job.external_job_id, getter)
    job.description_text = detailed.description_text
    if not job.location:
        job.location = detailed.location
    if not job.link:
        job.link = detailed.link
    return job


def _consider_one(job, log, profile, keys, getter, board):
    draft_box: dict = {}

    def jev(posting):
        decision = evaluate(
            lambda url, payload, headers: post_json(url, payload, headers),
            keys.typesafe,
            profile,
            posting,
            time.sleep,
        )
        return decision.stage, decision.reason, decision.model

    def questions_for(posting):
        if posting.portal == "greenhouse":
            return fetch_greenhouse_questions(board, posting.external_job_id, getter)
        url = posting.apply_url or posting.link
        if not url:
            return []
        return fetch_rendered_questions(url)

    def drafter(posting, questions):
        pending = needs_model(questions)
        supplied = {}
        if pending:
            status, body = post_json(
                "https://api.openai.com/v1/chat/completions",
                {
                    "model": keys.answer_model,
                    "response_format": {"type": "json_object"},
                    "messages": model_prompt(profile, posting.title, pending, company=posting.company, description=posting.description_text),
                },
                {"Authorization": f"Bearer {keys.openai}"},
            )
            if status != 200:
                raise StopRun(f"answer model returned {status}")
            supplied = parse_model_answers(body.decode("utf-8"))
        draft = draft_answers(questions, supplied)
        if any(field.kind == "attach" for field in draft.fields) and not (repo_root() / "resume.pdf").exists():
            draft = Draft(draft.fields, "blocked", "resume.pdf is missing")
        draft_box["draft"] = draft_payload(draft)
        return draft

    records = consider(
        job,
        seen=log.contains(job.portal, job.external_job_id),
        profile=profile,
        keys=keys,
        timestamp=stamp(utc_now()),
        jev=jev,
        questions_for=questions_for,
        drafter=drafter,
        retry=log.retryable(job.portal, job.external_job_id),
    )
    return records, draft_box.get("draft")


def repo_root() -> Path:
    here = Path.cwd()
    for candidate in (here, *here.parents):
        if (candidate / "data" / "ats-board-directory.csv").exists() and (candidate / "pyproject.toml").exists():
            return candidate
    raise SystemExit("Run this from the job-applications repo.")


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))

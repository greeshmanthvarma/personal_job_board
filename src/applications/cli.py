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
from applications.log import ApplicationLog, save_draft, latest_by_job
from applications.models import Record
from applications.page import render_page
from applications.pipeline import Keys, StopRun, consider, draft_payload, keyword_stage
from applications.portals import BoardError, fetch_board, fetch_greenhouse_job, fetch_greenhouse_questions, questions_from_html
from applications.schedule import BoardState, advance, is_due, load_schedule, save_schedule, stamp, utc_now
from applications.runstate import save_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="applications")
    sub = parser.add_subparsers(dest="command", required=True)
    poll = sub.add_parser("poll", help="Poll due boards through drafts")
    poll.add_argument("--limit", type=int)
    poll.add_argument('--draft-only', action='store_true', help='Prepare answers without submitting')
    poll.add_argument('--submit-limit', type=int, default=1, help='Maximum Ashby submission attempts per workflow run (default: 1)')
    poll.add_argument("--backlog", action="store_true", help="One-time scan of all boards and open postings regardless of posting age; reopen only age-based rejections")
    poll.add_argument("--vendor", choices=("greenhouse", "ashby", "lever"))
    poll.add_argument('--board', help='Restrict the workflow to one company board slug')
    poll.add_argument('--job-id', help='Restrict a scoped board workflow to one job ID; screening still applies')
    poll.add_argument('--approve-screening', action='store_true', help='Explicit human approval of the scoped job fit only; hard eligibility and submission safety checks still apply')
    poll.add_argument("--data-dir", type=Path)
    poll.add_argument("--recheck-location", action="store_true", help="Re-screen pre-model location uncertainties, including recently checked Ashby boards")
    page = sub.add_parser("page", help="Regenerate data/applications.html")
    page.add_argument("--data-dir", type=Path)
    submit = sub.add_parser('submit', help='Submit one complete Ashby draft, with verified confirmation')
    submit.add_argument('--portal', choices=('ashby',), required=True)
    submit.add_argument('--job-id', required=True)
    submit.add_argument('--data-dir', type=Path)
    args = parser.parse_args(argv)
    root = repo_root()
    load_env(root / ".env")
    data = args.data_dir or (root / "data")
    if args.command == 'submit':
        from applications.submission import run_submission, SubmissionBlocked
        try:
            return run_submission(data, root/'resume.pdf', args.portal, args.job_id)
        except SubmissionBlocked as err:
            print(f'Submission blocked: {err}')
            return 2
    if args.command == "page":
        render_page(data / "applications.csv", data / "applications.html", data / "drafts.json")
        print(data / "applications.html")
        return 0
    if args.submit_limit < 1:
        parser.error('--submit-limit must be at least 1; use --draft-only to disable submission')
    if args.job_id and not (args.board and args.vendor):
        parser.error('--job-id requires --board and --vendor')
    if args.approve_screening and not args.job_id:
        parser.error('--approve-screening requires --job-id, --board, and --vendor')
    if args.approve_screening:
        approval = data/'screening-approval.json'
        import json
        approval.parent.mkdir(parents=True, exist_ok=True)
        approval.write_text(json.dumps({'identity': f'{args.vendor}\t{args.job_id}', 'board': args.board, 'timestamp': stamp(utc_now())}), encoding='utf-8')
    return poll_boards(root, data, limit=args.limit, vendor=args.vendor, recheck_location=args.recheck_location, backlog=args.backlog, draft_only=args.draft_only, submit_limit=args.submit_limit, board_slug=args.board, job_id=args.job_id)


def poll_boards(root: Path, data: Path, limit: int | None, vendor: str | None, recheck_location: bool = False, backlog: bool = False, draft_only: bool = False, submit_limit: int = 1, board_slug: str | None = None, job_id: str | None = None) -> int:
    from applications.submission import execution_lock
    with execution_lock(data):
        return _tracked_poll_boards(root, data, limit, vendor, recheck_location, backlog, draft_only, submit_limit, board_slug, job_id)


def _tracked_poll_boards(root: Path, data: Path, limit: int | None, vendor: str | None, recheck_location: bool = False, backlog: bool = False, draft_only: bool = False, submit_limit: int = 1, board_slug: str | None = None, job_id: str | None = None) -> int:
    if (data/'submission.lock').exists():
        raise StopRun('A submission is active or needs review; polling is paused.')
    run = {'status': 'running', 'pid': os.getpid(), 'started_at': stamp(utc_now()), 'processed_boards': 0, 'target_boards': 0, 'current_board': '', 'message': ''}
    save_run(data / 'scan-state.json', run)
    try:
        result = _poll_boards(root, data, limit, vendor, recheck_location, run, backlog, draft_only, submit_limit, board_slug, job_id)
        run['status'] = 'completed' if result == 0 else 'stopped'
        return result
    except KeyboardInterrupt:
        run['status'] = 'interrupted'
        run['message'] = 'Scan interrupted; saved progress is retained.'
        raise
    except Exception as err:
        run['status'] = 'failed'
        # Do not persist exception payloads, which could contain credentials.
        run['message'] = f'Unexpected {type(err).__name__}; see terminal output.'
        raise
    finally:
        save_run(data / 'scan-state.json', run)
        render_page(data / 'applications.csv', data / 'applications.html', data / 'drafts.json')


def _poll_boards(root: Path, data: Path, limit: int | None, vendor: str | None, recheck_location: bool, run: dict, backlog: bool = False, draft_only: bool = False, submit_limit: int = 1, board_slug: str | None = None, job_id: str | None = None) -> int:
    boards = load_boards(data / "ats-board-directory.csv")
    if vendor:
        boards = [board for board in boards if board.vendor == vendor]
    if board_slug:
        boards = [board for board in boards if board.slug.casefold() == board_slug.casefold()]
    states = load_schedule(data / "board-schedule.json")
    now = utc_now()
    log = ApplicationLog(data / "applications.csv", recheck_location=recheck_location, backlog=backlog)
    import json
    approval_path = data/'screening-approval.json'
    approval = json.loads(approval_path.read_text()) if approval_path.exists() else {}
    approved_identity = approval.get('identity', '') if job_id and approval.get('identity') == f'{vendor}\t{job_id}' and approval.get('board', '').casefold() == (board_slug or '').casefold() else ''
    log.screening_approval = approved_identity
    due = [board for board in boards if backlog or is_due(states.get(board.key), now) or log.recheck_board(board)]
    if limit is not None:
        due = due[:limit]
    run['target_boards'] = len(due)
    save_run(data / 'scan-state.json', run)
    render_page(data / 'applications.csv', data / 'applications.html', data / 'drafts.json')
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
    submitted_attempts = 0
    # Resume saved complete drafts before discovering more jobs. Submitted and
    # ambiguous attempts remain protected by the durable submission journal.
    if not draft_only:
        for row in latest_by_job(log.rows):
            if job_id and row.external_job_id != job_id:
                continue
            if row.stage != 'drafted' or row.portal != 'ashby' or (vendor and vendor != row.portal):
                continue
            if board_slug and not any(row.link.startswith(f'https://jobs.ashbyhq.com/{board.slug}/') for board in boards):
                continue
            try:
                submit_workflow_draft(root, data, row)
            except StopRun as err:
                run['message'] = err.message
                print(err.message)
                return 2
            submitted_attempts += 1
            if submitted_attempts >= submit_limit:
                run['message'] = 'Submission attempt limit reached; remaining work is retained for the next run.'
                return 0
        log = ApplicationLog(data/'applications.csv', recheck_location=recheck_location, backlog=backlog)
        log.screening_approval = approved_identity
    for board in due:
        if held:
            break
        run['current_board'] = board.key
        save_run(data / 'scan-state.json', run)
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
            run['processed_boards'] += 1
            save_run(data / 'scan-state.json', run)
            render_page(data / 'applications.csv', data / 'applications.html', data / 'drafts.json')
            continue
        for job in fetched_jobs:
            if job_id and job.external_job_id != job_id:
                continue
            human_approved = job.identity == approved_identity and log.latest.get(job.identity) == 'jev_no'
            if log.contains(job.portal, job.external_job_id) and not human_approved:
                continue
            try:
                job = _hydrate(board, job, getter)
                records_and_draft = _consider_one(job, log, profile, keys, getter, board, backlog=backlog)
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
            if not draft_only and records and records[-1].stage == 'drafted' and job.portal == 'ashby':
                try:
                    submit_workflow_draft(root, data, records[-1])
                except StopRun as err:
                    held = True
                    message = err.message
                else:
                    submitted_attempts += 1
                    if submitted_attempts >= submit_limit:
                        held = True
                        message = 'Submission attempt limit reached; remaining work is retained for the next run.'
                log = ApplicationLog(data/'applications.csv', recheck_location=recheck_location, backlog=backlog)
                log.screening_approval = approved_identity
                if held:
                    break
        if held:
            held_state = states.get(board.key) or BoardState()
            held_state.next_check = stamp(utc_now())
            held_state.lever_host = fetched_host
            states[board.key] = held_state
        else:
            updated = advance(state, ok=True, job_count=len(fetched_jobs), now=utc_now(), status=fetched_status)
            if job_id:
                updated.next_check = stamp(utc_now())  # Other jobs on this board were not processed.
            updated.lever_host = fetched_host
            states[board.key] = updated
        save_schedule(data / "board-schedule.json", states)
        if not held:
            run['processed_boards'] += 1
        save_run(data / 'scan-state.json', run)
        render_page(data / "applications.csv", data / "applications.html", data / "drafts.json")
    render_page(data / "applications.csv", data / "applications.html", data / "drafts.json")
    if held:
        run['message'] = message
        print(message)
        return 2
    print(f"polled {len(due)} boards")
    return 0


def submit_workflow_draft(root, data, row, *, submitter=None):
    """Called only while poll_boards owns the shared execution lock."""
    if row.portal != 'ashby' or row.stage != 'drafted':
        return False
    from applications.submission import _run_submission, SubmissionBlocked
    try:
        result = _run_submission(data, root/'resume.pdf', row.portal, row.external_job_id, submitter=submitter, workflow=True)
    except SubmissionBlocked as err:
        log = ApplicationLog(data/'applications.csv')
        log.append(Record(stamp(utc_now()), row.portal, row.external_job_id, row.job, row.company, row.link, 'blocked', f'Needs your input: {err}', row.model))
        raise StopRun(f'Submission paused: {err}') from err
    if result != 0:
        raise StopRun('Submission needs your input; inspect the blocked entry and attempt evidence before retrying.')
    return True


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


def _consider_one(job, log, profile, keys, getter, board, backlog=False):
    draft_box: dict = {}

    def jev(posting):
        if posting.identity == getattr(log, 'screening_approval', ''):
            return 'jev_yes', 'Explicit human approval of this job fit; global AI threshold unchanged', 'human-approval'
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
        draft_box['draft']['questions'] = [{'label': q.label, 'required': q.required, 'kind': q.kind, 'options': list(q.options)} for q in questions]
        return draft

    records = consider(
        job,
        seen=log.contains(job.portal, job.external_job_id) and not (job.identity == getattr(log, 'screening_approval', '') and log.latest.get(job.identity) == 'jev_no'),
        profile=profile,
        keys=keys,
        timestamp=stamp(utc_now()),
        jev=jev,
        questions_for=questions_for,
        drafter=drafter,
        retry=backlog or log.retryable(job.portal, job.external_job_id),
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

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
from applications.schedule import BoardState, advance, is_due, load_schedule, save_schedule, stamp, utc_now, select_due
from applications.runstate import save_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="applications")
    sub = parser.add_subparsers(dest="command", required=True)
    poll = sub.add_parser("poll", help="Poll due boards through drafts")
    poll.add_argument("--limit", type=int)
    poll.add_argument("--backlog", action="store_true", help="One-time scan of all boards and open postings regardless of posting age; reopen only age-based rejections")
    poll.add_argument("--vendor", choices=("greenhouse", "ashby", "lever"))
    poll.add_argument('--board', help='Restrict the workflow to one company board slug')
    poll.add_argument('--job-id', help='Restrict a scoped board workflow to one job ID; screening still applies')
    poll.add_argument("--data-dir", type=Path)
    poll.add_argument('--assessment-limit', type=int, default=50, help='Maximum new Jev assessments per scan; discovery continues beyond this budget')
    poll.add_argument("--recheck-location", action="store_true", help="Re-screen pre-model location uncertainties, including recently checked Ashby boards")
    page = sub.add_parser("page", help="Regenerate data/applications.html")
    page.add_argument("--data-dir", type=Path)
    serve = sub.add_parser('serve', help='Private local job board and application tracker')
    serve.add_argument('--port', type=int, default=8765)
    serve.add_argument('--data-dir', type=Path)
    serve.add_argument('--remote', action='store_true', help='Use authenticated Railway storage; never fall back to local data')
    sub.add_parser('host', help='Authenticated Railway backend with supervised scheduled discovery')
    snapshot = sub.add_parser('snapshot', help='Create a private validated snapshot; never includes secrets/profile')
    snapshot.add_argument('--data-dir', type=Path)
    snapshot.add_argument('--output',type=Path,required=True)
    restore = sub.add_parser('restore', help='Restore a validated snapshot into an empty directory only')
    restore.add_argument('--source',type=Path,required=True)
    restore.add_argument('--data-dir',type=Path,required=True)
    prepare = sub.add_parser('prepare', help='Prepare answers for one manually selected job; never submit')
    prepare.add_argument('--portal', required=True, choices=('ashby','greenhouse','lever'))
    prepare.add_argument('--job-id', required=True)
    prepare.add_argument('--data-dir', type=Path)
    args = parser.parse_args(argv)
    root = repo_root()
    load_env(root / ".env")
    data = getattr(args, 'data_dir', None) or (root / "data")
    if args.command in {'snapshot','restore'}:
        from applications.snapshots import create_snapshot,restore_snapshot
        try:
            if args.command=='snapshot':create_snapshot(data,args.output)
            else:restore_snapshot(args.source,data)
        except (ValueError,OSError,KeyError):
            print('Snapshot operation failed; check validated input and an empty restore destination.')
            return 2
        print('Snapshot operation completed; private contents omitted.')
        return 0
    if args.command == 'host':
        from applications.hosting import host_board
        return host_board(root)
    if args.command == 'serve':
        from applications.server import serve_board
        client = None
        if args.remote:
            from applications.proxy import RemoteClient
            try:
                client = RemoteClient(os.environ.get('BOARD_REMOTE_URL',''), os.environ.get('BOARD_API_TOKEN',''))
            except ValueError as err:
                parser.error(str(err))
        serve_board(data, args.port, client)
        return 0
    if args.command == 'prepare':
        try:
            return prepare_selected(root, data, args.portal, args.job_id)
        except (StopRun, BoardError, NetworkError) as err:
            print(getattr(err, 'message', str(err)))
            return 2
    if args.command == "page":
        render_page(data / "applications.csv", data / "applications.html", data / "drafts.json")
        print(data / "applications.html")
        return 0
    if args.job_id and not (args.board and args.vendor):
        parser.error('--job-id requires --board and --vendor')
    if args.assessment_limit < 0:
        parser.error('--assessment-limit cannot be negative')
    return poll_boards(root, data, limit=args.limit, vendor=args.vendor, recheck_location=args.recheck_location, backlog=args.backlog, board_slug=args.board, job_id=args.job_id, assessment_limit=args.assessment_limit)


def poll_boards(root: Path, data: Path, limit: int | None, vendor: str | None, recheck_location: bool = False, backlog: bool = False, board_slug: str | None = None, job_id: str | None = None, assessment_limit: int = 50) -> int:
    from applications.locking import execution_lock
    with execution_lock(data):
        return _tracked_poll_boards(root, data, limit, vendor, recheck_location, backlog, board_slug, job_id, assessment_limit)


def _tracked_poll_boards(root: Path, data: Path, limit: int | None, vendor: str | None, recheck_location: bool = False, backlog: bool = False, board_slug: str | None = None, job_id: str | None = None, assessment_limit: int = 50) -> int:
    run = {'status': 'running', 'pid': os.getpid(), 'started_at': stamp(utc_now()), 'processed_boards': 0, 'target_boards': 0, 'current_board': '', 'message': ''}
    save_run(data / 'scan-state.json', run)
    try:
        result = _poll_boards(root, data, limit, vendor, recheck_location, run, backlog, board_slug, job_id, assessment_limit)
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


def _poll_boards(root: Path, data: Path, limit: int | None, vendor: str | None, recheck_location: bool, run: dict, backlog: bool = False, board_slug: str | None = None, job_id: str | None = None, assessment_limit: int = 50) -> int:
    import hashlib
    from applications.listings import fit_score, load_listings, save_listings
    from applications.keywords import title_decision, location_decision
    from applications.eligibility import eligibility_reason
    boards = load_boards(data / "ats-board-directory.csv")
    if vendor:
        boards = [board for board in boards if board.vendor == vendor]
    if board_slug:
        boards = [board for board in boards if board.slug.casefold() == board_slug.casefold()]
    states = load_schedule(data / "board-schedule.json")
    now = utc_now()
    log = ApplicationLog(data / "applications.csv", recheck_location=recheck_location, backlog=backlog)
    due = select_due(boards, states, now, limit, backlog)
    if recheck_location:
        due = [board for board in boards if log.recheck_board(board) or board in due]
        if limit is not None:
            due = due[:limit]
    all_due = select_due(boards, states, now)
    run['due_boards'] = len(all_due)
    known_due = [states[b.key].next_check for b in all_due if b.key in states and states[b.key].next_check]
    run['oldest_due_at'] = min(known_due) if known_due else ''
    run['target_boards'] = len(due)
    save_run(data / 'scan-state.json', run)
    render_page(data / 'applications.csv', data / 'applications.html', data / 'drafts.json')
    keys = Keys(
        typesafe=os.environ.get("TYPESAFE_API_KEY", "").strip(),
        openai=os.environ.get("OPENAI_API_KEY", "").strip(),
        answer_model=os.environ.get("ANSWER_MODEL", "").strip() or "gpt-6-luna",
    )
    profile_path = root / "profile.md"
    profile = os.environ.get('PROFILE_TEXT','') or (profile_path.read_text(encoding="utf-8") if profile_path.exists() else "")
    hosted = os.environ.get('APPLICATIONS_HOSTED') == '1'
    batch_deadline = time.monotonic() + 1200 if hosted else float('inf')
    board_deadline = batch_deadline
    def cloud_get(url):
        from applications.hosted_http import hosted_get
        remaining = min(board_deadline,batch_deadline) - time.monotonic()
        if remaining <= 0:
            raise NetworkError('Scan deadline reached')
        return hosted_get(url, timeout=min(30,remaining))
    getter = paced_get(cloud_get if hosted else get_bytes, production_limiter())
    held = False
    message = ""
    assessed = 0
    jev_available = bool(keys.typesafe and profile.strip())
    for board in due:
        if time.monotonic() >= batch_deadline:
            break
        board_deadline = min(batch_deadline,time.monotonic()+300)
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
        collected = []
        assessments = {}
        complete = not bool(job_id)
        previous_listings = load_listings(data)
        for job in sorted(fetched_jobs, key=lambda j: j.posted_at.timestamp() if j.posted_at else 0, reverse=True):
            if time.monotonic() >= board_deadline:
                complete = False
                break
            if job_id and job.external_job_id != job_id:
                continue
            if not title_decision(job.title).ok or location_decision(job.location).action == 'reject':
                continue
            try:
                job = _hydrate(board, job, getter)
            except (BoardError, NetworkError) as err:
                complete = False
                log.append(
                    Record(
                        timestamp=stamp(utc_now()),
                        portal=job.portal,
                        external_job_id=job.external_job_id,
                        job=job.title,
                        company=job.company,
                        link=job.link,
                        stage="failed",
                        reason=getattr(err, 'message', str(err)),
                    )
                )
                collected.append(job)
                continue
            collected.append(job)
            if not job.is_listed or eligibility_reason(job.description_text) or not job.description_text.strip():
                continue
            fingerprint = hashlib.sha256((job.title+job.location+job.description_text+profile).encode()).hexdigest()
            if previous_listings.get(job.identity, {}).get('assessment_fingerprint') == fingerprint:
                continue
            if jev_available and assessed < assessment_limit:
                assessment_deadline = min(board_deadline,time.monotonic()+90)
                def cloud_post(url, payload, headers):
                    from applications.jev import ENDPOINT
                    if url != ENDPOINT:
                        raise NetworkError('Assessment destination rejected')
                    remaining = assessment_deadline-time.monotonic()
                    if remaining <= 0:
                        raise NetworkError('Assessment deadline reached')
                    from applications.hosted_http import hosted_post
                    return hosted_post(url,payload,headers,timeout=min(30,remaining))
                def cloud_sleep(seconds):
                    remaining=assessment_deadline-time.monotonic()
                    if remaining<=seconds:
                        raise NetworkError('Assessment deadline reached')
                    time.sleep(seconds)
                try:
                    decision = evaluate(cloud_post if hosted else post_json, keys.typesafe, profile, job, cloud_sleep if hosted else time.sleep)
                except (JevError, NetworkError):
                    jev_available = False
                    run['message'] = 'Jev unavailable; discovery continues. Unassessed jobs remain visible.'
                else:
                    assessments[job.identity] = {'reason': decision.reason, 'fingerprint': fingerprint}
                    assessed += 1
        save_listings(data, collected, stamp(utc_now()), board=board, complete=complete, assessments=assessments)
        if held:
            held_state = states.get(board.key) or BoardState()
            held_state.next_check = stamp(utc_now())
            held_state.lever_host = fetched_host
            states[board.key] = held_state
        else:
            saved = load_listings(data)
            strong_match = any(
                value.get('board_key') == board.key
                and value.get('is_listed') and not value.get('eligibility_reason')
                and (fit_score(value.get('assessment', '')) or 0) >= .75
                for value in saved.values()
            )
            updated = advance(state, ok=True, job_count=len(fetched_jobs), now=utc_now(), status=fetched_status, strong_match=strong_match)
            if job_id or not complete:
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


def _consider_one(job, log, profile, keys, getter, board, backlog=False, preparing=False):
    draft_box: dict = {}

    def jev(posting):
        if preparing:
            return 'jev_yes', 'User-selected answer preparation; not an application', ''
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
            if not keys.openai:
                raise StopRun('OPENAI_API_KEY is needed for personalized narrative answers')
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
        seen=False if preparing else log.contains(job.portal, job.external_job_id),
        profile=profile,
        keys=Keys(keys.typesafe, keys.openai or 'deterministic-only', keys.answer_model) if preparing else keys,
        timestamp=stamp(utc_now()),
        jev=jev,
        questions_for=questions_for,
        drafter=drafter,
        retry=backlog or log.retryable(job.portal, job.external_job_id),
    )
    return records, draft_box.get("draft")


def prepare_selected(root, data, portal, job_id):
    from applications.listings import load_listings
    from applications.models import JobPosting, Board
    from applications.eligibility import eligibility_reason
    from applications.locking import execution_lock
    with execution_lock(data):
        item = load_listings(data).get(f'{portal}\t{job_id}')
        if not item or not item.get('is_listed') or eligibility_reason(item.get('description','')):
            print('Refresh a currently open eligible listing before preparing answers.')
            return 2
        slug = item['board_key'].split(':',1)[1]
        job = JobPosting(portal,job_id,item['title'],item['company'],item['location'],item['link'],item['description'],board_slug=slug,apply_url=item['link'])
        profile = (root/'profile.md').read_text() if (root/'profile.md').exists() else ''
        if not profile.strip():
            print('profile.md is missing')
            return 2
        keys = Keys('explicit-selection',os.environ.get('OPENAI_API_KEY',''),os.environ.get('ANSWER_MODEL','') or 'gpt-6-luna')
        # Preparation is an explicit user selection, not a fit-gated application.
        records, draft = _consider_one(job, ApplicationLog(data/'applications.csv'), profile, keys, paced_get(get_bytes,production_limiter()), Board(portal,item['company'],slug), backlog=True, preparing=True)
        if draft:
            save_draft(data/'drafts.json',job.identity,draft)
            print(draft['reason'])
            return 0 if draft['stage']=='drafted' else 2
        print(records[-1].reason if records else 'No answers prepared')
        return 2


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

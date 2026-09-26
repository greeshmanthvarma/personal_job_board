"""Explicit one-job submission with durable, conservative duplicate protection."""

import hashlib
import json
import os
import fcntl
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

from applications.log import ApplicationLog, load_drafts, latest_by_job
from applications.models import Record
from applications.page import render_page
from applications.runstate import load_run
from applications.schedule import stamp, utc_now


class SubmissionBlocked(Exception):
    pass


@contextmanager
def execution_lock(data: Path):
    data.mkdir(parents=True, exist_ok=True)
    with (data/'execution.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as err:
            raise SubmissionBlocked('Another poll or submission command is active.') from err
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def attempt_path(data: Path, identity: str) -> Path:
    return data / 'submission-attempts' / (hashlib.sha256(identity.encode()).hexdigest() + '.json')


def begin_attempt(data: Path, identity: str, evidence: dict) -> Path:
    path = attempt_path(data, identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8') as handle:
            json.dump({'identity': identity, 'status': 'prepared', 'timestamp': stamp(utc_now()), **evidence}, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as err:
        previous = json.loads(path.read_text())
        if previous.get('status') == 'reviewed_preclick' and not previous.get('clicking_at'):
            fresh = {'identity': identity, 'status': 'prepared', 'timestamp': stamp(utc_now()), **evidence, 'previous_attempts': [*previous.get('previous_attempts', []), {k: v for k, v in previous.items() if k != 'previous_attempts'}]}
            temporary = path.with_suffix('.tmp')
            with temporary.open('w') as handle:
                json.dump(fresh, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
            return path
        raise SubmissionBlocked('An attempt already exists. Review its outcome; automatic retries are disabled.') from err
    return path


def finish_attempt(data: Path, identity: str, status: str, evidence: dict) -> None:
    path = attempt_path(data, identity)
    value = json.loads(path.read_text())
    value.update(evidence)
    value.update(status=status, updated_at=stamp(utc_now()))
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def review_preclick_attempt(data: Path, identity: str, reason: str):
    """Explicit review only; never clears an unknown or clicked attempt."""
    with execution_lock(data):
        previous = json.loads(attempt_path(data, identity).read_text())
        if previous.get('status') != 'blocked' or previous.get('clicking_at'):
            raise SubmissionBlocked('Only a verified pre-click blocked attempt can be reviewed for retry.')
        finish_attempt(data, identity, 'reviewed_preclick', {'review_reason': reason})


def run_submission(data: Path, resume: Path, portal: str, job_id: str, *, submitter=None) -> int:
    with execution_lock(data):
        return _run_submission(data, resume, portal, job_id, submitter=submitter)


def _run_submission(data: Path, resume: Path, portal: str, job_id: str, *, submitter=None, workflow: bool = False) -> int:
    if portal != 'ashby':
        raise SubmissionBlocked('Only the tested Ashby adapter is supported.')
    if not workflow and load_run(data/'scan-state.json').get('status') == 'running':
        raise SubmissionBlocked('Stop the active polling run before submitting.')
    data.mkdir(parents=True, exist_ok=True)
    lock = data/'submission.lock'
    try:
        handle = lock.open('x')
    except FileExistsError as err:
        raise SubmissionBlocked('Submission lock exists; review the previous process before removing it.') from err
    try:
        handle.write(str(os.getpid()))
        handle.close()
        identity = f'{portal}\t{job_id}'
        log = ApplicationLog(data/'applications.csv')
        row = next((r for r in latest_by_job(log.rows) if r.portal == portal and r.external_job_id == job_id), None)
        draft = load_drafts(data/'drafts.json').get(identity)
        if row is None or row.stage != 'drafted' or not draft or draft.get('stage') != 'drafted':
            raise SubmissionBlocked('This job does not have a complete current draft.')
        parsed = urlparse(row.link)
        segments = parsed.path.strip('/').split('/')
        if parsed.scheme != 'https' or parsed.hostname != 'jobs.ashbyhq.com' or len(segments) < 2 or segments[1] != job_id:
            raise SubmissionBlocked('Unexpected employer application URL.')
        url = f'https://jobs.ashbyhq.com/{segments[0]}/{job_id}/application'
        journal = begin_attempt(data, identity, {'url': url, 'draft': draft})
        evidence_dir = journal.with_suffix('')
        evidence_dir.mkdir(exist_ok=True)
        clicked = False
        def before_click():
            nonlocal clicked
            finish_attempt(data, identity, 'clicking', {'clicking_at': stamp(utc_now())})
            clicked = True
        if submitter is None:
            from applications.ashby_submit import submit_ashby_url
            submitter = submit_ashby_url
        try:
            result = submitter(url, draft, resume, before_click, evidence_dir)
        except Exception as err:
            # Exceptions may contain submitted personal data; persist only their type.
            result = {'status': 'unknown' if clicked else 'blocked', 'reason': f'{type(err).__name__}: manual review required'}
        status = result.get('status')
        if status == 'confirmed' and not clicked:
            result = {'status': 'blocked', 'reason': 'Invalid confirmation without recorded submit attempt'}
            status = 'blocked'
        if status not in {'confirmed', 'unknown', 'blocked'}:
            result = {'status': 'unknown' if clicked else 'blocked', 'reason': 'Unrecognized adapter outcome'}
            status = result['status']
        finish_attempt(data, identity, status, result)
        stage = 'submitted' if status == 'confirmed' else 'blocked'
        reason = (result.get('confirmation') if stage == 'submitted' else result.get('reason')) or 'Manual review required'
        reason = f'{reason}. Evidence: {journal.relative_to(data)}'
        log.append(Record(stamp(utc_now()), portal, job_id, row.job, row.company, row.link, stage, reason, row.model))
        render_page(data/'applications.csv', data/'applications.html', data/'drafts.json')
        print(f'{row.company}: {stage}: {reason}')
        return 0 if stage == 'submitted' else 2
    finally:
        handle.close()
        lock.unlink(missing_ok=True)

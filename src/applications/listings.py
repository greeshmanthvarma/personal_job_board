"""Private listing feed. Posting age and AI uncertainty never exclude jobs."""
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from applications.keywords import title_decision, location_decision
from applications.eligibility import eligibility_reason
from applications.log import latest_by_job, load_records, load_drafts
from applications.storage import atomic_json, locked_data

def load_listings(data: Path) -> dict:
    path = data/'jobs.json'
    return json.loads(path.read_text()) if path.exists() else {}

@locked_data
def save_listings(data: Path, jobs: list, checked_at: str, *, board=None, complete=True, assessments=None):
    values = load_listings(data)
    present = {j.identity for j in jobs}
    if board and complete:
        for key, value in values.items():
            if value.get('board_key') == board.key and key not in present:
                value.update(is_listed=False, checked_at=checked_at)
    for job in jobs:
        if not title_decision(job.title).ok or location_decision(job.location).action == 'reject':
            continue
        previous = values.get(job.identity, {})
        if previous and any(previous.get(k) != v for k,v in [('title',job.title),('location',job.location),('description',job.description_text)]):
            previous = dict(previous, assessment='', assessment_fingerprint='')
        reason = eligibility_reason(job.description_text)
        value = dict(previous, identity=job.identity, portal=job.portal, job_id=job.external_job_id,
                     company=job.company, title=job.title, location=job.location, link=job.apply_url or job.link,
                     description=job.description_text, posted_at=job.posted_at.isoformat() if job.posted_at else '',
                     checked_at=checked_at, is_listed=job.is_listed, eligibility_reason=reason or '',
                     board_key=board.key if board else previous.get('board_key', ''),
                     location_uncertain=location_decision(job.location).action == 'uncertain')
        if assessments and job.identity in assessments:
            assessment = assessments[job.identity]
            value.update(assessment=assessment['reason'], assessment_fingerprint=assessment['fingerprint'])
        values[job.identity] = value
    data.mkdir(parents=True, exist_ok=True)
    atomic_json(data/'jobs.json', values)

def fit_score(reason: str):
    matches = re.findall(r'(role_family|level|responsibilities|qualifications)\s+(?:yes|no|uncertain)\s+\((\d+(?:\.\d+)?)\)', reason)
    scores = dict(matches)
    if len(scores) != 4:
        return None
    return sum(float(v) for v in scores.values()) / 4

def ranking(job: dict, now=None) -> tuple[float, float]:
    now = now or datetime.now(timezone.utc)
    recency = 0.0
    try:
        posted = datetime.fromisoformat(job.get('posted_at', '').replace('Z', '+00:00'))
        posted = posted if posted.tzinfo else posted.replace(tzinfo=timezone.utc)
        recency = math.exp(-max(0, (now-posted).total_seconds()) / (7*86400))
    except (ValueError, TypeError):
        pass
    fit = fit_score(job.get('assessment', ''))
    return .7*(fit if fit is not None else 0) + .3*recency, recency

def list_board_jobs(data: Path) -> list[dict]:
    from applications.tracking import load_tracking
    values = load_listings(data)
    tracking = load_tracking(data)
    drafts = load_drafts(data/'drafts.json')
    historical = load_records(data/'applications.csv')
    past_assessments = {f'{r.portal}\t{r.external_job_id}': r.reason for r in historical if r.model.startswith('jev') and fit_score(r.reason) is not None}
    rows = latest_by_job(historical)
    for row in rows:
        key = f'{row.portal}\t{row.external_job_id}'
        historic_match = row.stage in {'jev_yes','jev_no','drafted','blocked','failed','submitted'} or (row.stage=='keyword_reject' and row.reason.startswith(('posted more than 24 hours ago','posted date missing')))
        if not historic_match and key not in tracking:
            continue
        if key not in values:
            values[key] = {'identity': key, 'portal': row.portal, 'job_id': row.external_job_id, 'company': row.company, 'title': row.job, 'location': '', 'link': row.link, 'posted_at': '', 'checked_at': '', 'is_listed': None, 'eligibility_reason': ''}
        value = values[key]
        if key in past_assessments and not value.get('assessment'):
            value['assessment'] = past_assessments[key]
            value['assessment_historical'] = True
        value['history_reason'] = row.reason
        value['history_stage'] = row.stage
    result = []
    for key, value in values.items():
        if value.get('eligibility_reason') and key not in tracking:
            continue
        value = dict(value)
        unknown = value.get('history_stage') == 'blocked' and ('No explicit employer confirmation' in value.get('history_reason','') or 'unknown' in value.get('history_reason','').lower())
        default = 'needs_verification' if unknown else ('applied' if value.get('history_stage') == 'submitted' else 'new')
        value.update(status=default, notes='', applied_at='', updated_at='')
        value.update(tracking.get(key, {}))
        value['fit'] = fit_score(value.get('assessment',''))
        value['priority'], value['recency'] = ranking(value)
        value['fields'] = drafts.get(key, {}).get('fields', [])
        result.append(value)
    return sorted(result, key=lambda j: (j['priority'],j.get('posted_at','')), reverse=True)

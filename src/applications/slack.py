"""Optional Slack alerts for recent, untracked strong JEV matches."""
import http.client
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from applications.http import NetworkError, ssl_context
from applications.listings import fit_score, load_listings, recent_posting
from applications.proxy import NoRedirect
from applications.schedule import stamp, utc_now
from applications.storage import atomic_json, snapshot_lock
from applications.tracking import load_tracking

NOTIFICATION_THRESHOLD = 0.70


def notification_match(reason):
    checks = re.findall(r'(role_family|level|responsibilities|qualifications)\s+(?:yes|no|uncertain)\s+\((\d+(?:\.\d+)?)\)', reason)
    scores = dict(checks)
    return len(checks) == len(scores) == 4 and all(
        NOTIFICATION_THRESHOLD <= float(score) <= 1 for score in scores.values())


def validate_webhook(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'hooks.slack.com'
            or parsed.query or parsed.fragment
            or not re.fullmatch(r'/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', parsed.path)):
        raise ValueError('SLACK_WEBHOOK_URL must be a Slack incoming webhook URL')


def send_webhook(url, payload):
    validate_webhook(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl_context()))
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with opener.open(request, timeout=10) as response:
            if response.status != 200 or response.read(1024).strip() != b'ok':
                raise NetworkError('Slack did not acknowledge the notification')
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        # Webhook paths are secrets; omit exceptions and response bodies.
        raise NetworkError('Slack notification request failed') from None


def formatted_posted_at(value):
    try:
        posted = datetime.fromisoformat((value or '').replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return 'Unknown'
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    local = posted.astimezone(ZoneInfo('America/Los_Angeles'))
    return f"{local:%b} {local.day}, {local.year} at {local.hour % 12 or 12}:{local:%M %p %Z}"


def message(job):
    score = fit_score(job.get('assessment', ''))
    text = (f"Strong JEV match: {job.get('title', '')} at {job.get('company', '')}\n"
            f"Location: {job.get('location') or 'Not specified'}\n"
            f"JEV fit score: {score:.0%}\n"
            f"Posted: {formatted_posted_at(job.get('posted_at'))}\n{job.get('link', '')}")[:3000]
    return {'text': text, 'blocks': [
        {'type': 'section', 'text': {'type': 'plain_text', 'text': text}},
    ], 'unfurl_links': False, 'unfurl_media': False}


def notify_matches(data, webhook, *, send=None, limit=20, now=None,
                   state_name='slack-notifications.json', validate=validate_webhook):
    """Run under the poll execution lock; failed sends retry next scan."""
    if not webhook:
        return 0
    validate(webhook)
    send = send or send_webhook
    now = now or utc_now()
    path = data / state_name
    with snapshot_lock(data):
        delivered = json.loads(path.read_text()) if path.exists() else {}
    tracking = load_tracking(data)
    jobs = sorted(load_listings(data).values(), key=lambda j: j.get('posted_at', ''), reverse=True)
    sent = 0
    for job in jobs:
        identity = job['identity']
        if (identity in delivered or tracking.get(identity, {}).get('status', 'new') != 'new'
                or job.get('is_listed') is not True or job.get('eligibility_reason')
                or job.get('location_uncertain') or not recent_posting(job, now)
                or not notification_match(job.get('assessment', ''))):
            continue
        if sent >= limit:
            break
        if sent:
            time.sleep(1.1)
        send(webhook, message(job))
        delivered[identity] = stamp(now)
        with snapshot_lock(data):
            atomic_json(path, delivered)
        sent += 1
    return sent

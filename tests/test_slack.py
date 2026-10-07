import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from applications.http import NetworkError
from applications.slack import formatted_posted_at, notify_matches, validate_webhook

URL = 'https://hooks.slack.com/services/Ttest/Btest/secret'
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
REASON = 'yes: role_family yes (0.90); level yes (0.90); responsibilities yes (0.90); qualifications yes (0.90)'


class SlackTests(unittest.TestCase):
    def test_posted_time_uses_pacific_timezone_and_daylight_saving(self):
        self.assertEqual(formatted_posted_at('2026-10-06T21:30:00Z'), 'Oct 6, 2026 at 2:30 PM PDT')
        self.assertEqual(formatted_posted_at('2026-01-06T21:30:00+00:00'), 'Jan 6, 2026 at 1:30 PM PST')
        self.assertEqual(formatted_posted_at('2026-10-06T01:30:00'), 'Oct 5, 2026 at 6:30 PM PDT')
        self.assertEqual(formatted_posted_at('invalid'), 'Unknown')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.job = dict(identity='ashby\t1', title='Engineer', company='Example',
                        location='Remote US', posted_at=NOW.isoformat(), is_listed=True,
                        assessment=REASON, link='https://example.com/job')
        self.save([self.job])

    def save(self, jobs):
        (self.data / 'jobs.json').write_text(json.dumps({j['identity']: j for j in jobs}))

    def test_disabled_and_deduplicated(self):
        sends = []
        send = lambda url, body: sends.append(body)
        self.assertEqual(notify_matches(self.data, '', send=send, now=NOW), 0)
        self.assertEqual(notify_matches(self.data, URL, send=send, now=NOW), 1)
        self.assertEqual(notify_matches(self.data, URL, send=send, now=NOW), 0)
        self.assertIn('90%', sends[0]['text'])
        self.assertNotIn('actions', str(sends[0]))

    def test_failure_retries(self):
        def fail(*args):
            raise NetworkError('failed')
        with self.assertRaises(NetworkError):
            notify_matches(self.data, URL, send=fail, now=NOW)
        self.assertFalse((self.data / 'slack-notifications.json').exists())
        self.assertEqual(notify_matches(self.data, URL, send=lambda *args: None, now=NOW), 1)

    def test_filters(self):
        for changes in ({'assessment': ''}, {'assessment': REASON.replace('level yes (0.90)', 'level uncertain (0.69)')},
                        {'is_listed': False}, {'eligibility_reason': 'No'}, {'location': 'Berlin, Germany'},
                        {'posted_at': '2026-09-01'},
                        {'posted_at': '2026-10-07'}, {'posted_at': ''}):
            with self.subTest(changes=changes):
                self.save([dict(self.job, **changes)])
                self.assertEqual(notify_matches(self.data, URL, send=lambda *args: self.fail('sent'), now=NOW), 0)
        self.save([self.job])
        (self.data / 'tracking.json').write_text(json.dumps({self.job['identity']: {'status': 'skipped'}}))
        self.assertEqual(notify_matches(self.data, URL, send=lambda *args: self.fail('sent'), now=NOW), 0)

    def test_limit(self):
        self.save([dict(self.job, identity=f'ashby\t{i}') for i in range(3)])
        self.assertEqual(notify_matches(self.data, URL, send=lambda *args: None, limit=2, now=NOW), 2)
        self.assertEqual(notify_matches(self.data, URL, send=lambda *args: None, limit=2, now=NOW), 1)

    def test_seventy_percent_includes_cached_uncertain_assessments(self):
        reason = REASON.replace('yes:', 'uncertain:').replace('yes (0.90)', 'uncertain (0.70)')
        self.save([dict(self.job, assessment=reason)])
        self.assertEqual(notify_matches(self.data, URL, send=lambda *args: None, now=NOW), 1)

    def test_uncertain_location_can_notify_when_fit_passes(self):
        self.save([dict(self.job, location='Cupertino', location_uncertain=True)])
        self.assertEqual(notify_matches(self.data, URL, send=lambda *args: None, now=NOW), 1)

    def test_high_average_does_not_override_low_check(self):
        reason = REASON.replace('0.90', '1.00').replace('level yes (1.00)', 'level uncertain (0.69)')
        self.save([dict(self.job, assessment=reason)])
        self.assertEqual(notify_matches(self.data, URL, send=lambda *args: self.fail('sent'), now=NOW), 0)

    def test_rejects_other_destinations(self):
        for url in ('http://hooks.slack.com/services/T/B/S', 'https://example.com/services/T/B/S',
                    URL + '?secret=x', 'https://hooks.slack.com.evil.com/services/T/B/S'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_webhook(url)

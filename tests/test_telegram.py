import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from applications.http import NetworkError
from applications.telegram import notify_telegram, private_chat_ids, request

TOKEN = '12345:test_secret'
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


class TelegramTests(unittest.TestCase):
    def test_notify_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            reason = 'yes: role_family yes (0.90); level yes (0.90); responsibilities yes (0.90); qualifications yes (0.90)'
            job = dict(identity='ashby\t1', title='Engineer', company='Example',
                       location='Remote US', posted_at=NOW.isoformat(), is_listed=True,
                       assessment=reason, link='https://example.com/job')
            (data/'jobs.json').write_text(json.dumps({job['identity']: job}))
            calls = []
            api = lambda *args: calls.append(args)
            self.assertEqual(notify_telegram(data, TOKEN, '6789', api=api, now=NOW), 1)
            self.assertEqual(notify_telegram(data, TOKEN, '6789', api=api, now=NOW), 0)
            self.assertEqual(calls[0][1], 'sendMessage')
            self.assertEqual(calls[0][2]['chat_id'], '6789')
            self.assertIn('90%', calls[0][2]['text'])
            self.assertTrue((data/'telegram-notifications.json').exists())
            self.assertFalse((data/'slack-notifications.json').exists())

    def test_disabled_and_incomplete_configuration(self):
        self.assertEqual(notify_telegram(Path('/unused'), '', ''), 0)
        for token, chat in [('', '123'), (TOKEN, ''), (TOKEN, '-123'), ('bad', '123')]:
            with self.subTest(token=token, chat=chat), self.assertRaises(ValueError):
                notify_telegram(Path('/unused'), token, chat)

    def test_private_chat_discovery(self):
        updates = [{'message': {'chat': {'type': 'private', 'id': 123}}},
                   {'message': {'chat': {'type': 'group', 'id': -123}}},
                   {'message': {'chat': {'type': 'private', 'id': 123}}}, {}]
        self.assertEqual(private_chat_ids(TOKEN, api=lambda *args: updates), ['123'])

    def test_errors_do_not_expose_token(self):
        error = urllib.error.URLError('https://api.telegram.org/bot' + TOKEN)
        with patch('applications.telegram.urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = error
            with self.assertRaises(NetworkError) as caught:
                request(TOKEN, 'getUpdates', {})
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_api_rejection(self):
        with patch('applications.telegram.urllib.request.build_opener') as factory:
            response = factory.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"ok": false}'
            with self.assertRaises(NetworkError):
                request(TOKEN, 'sendMessage', {})

    def test_timeout_is_distinct_from_invalid_token(self):
        for error, expected in [
            (TimeoutError('secret'), 'timed out'),
            (urllib.error.HTTPError('https://api.telegram.org/bot'+TOKEN, 401, 'Unauthorized', {}, None), 'rejected the bot token'),
            (urllib.error.HTTPError('https://api.telegram.org/bot'+TOKEN, 409, 'Conflict', {}, None), 'another update consumer'),
        ]:
            with self.subTest(expected=expected), patch('applications.telegram.urllib.request.build_opener') as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaises(NetworkError) as caught:
                    request(TOKEN, 'getUpdates', {})
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn(TOKEN, str(caught.exception))

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


class TelegramButtonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.identity = 'ashby\t' + 'long-job-id' * 20
        (self.data/'jobs.json').write_text(json.dumps({self.identity: {'identity': self.identity}}))
        from applications.telegram import applied_callback
        self.query = {'id': 'query1', 'from': {'id': 6789},
                      'message': {'message_id': 42, 'chat': {'id': 6789, 'type': 'private'}},
                      'data': applied_callback(self.identity)}
        self.calls = []
        self.api = lambda *args: self.calls.append(args)

    def test_click_preserves_notes_and_duplicate_preserves_date(self):
        from applications.telegram import process_callback
        from applications.tracking import load_tracking
        (self.data/'tracking.json').write_text(json.dumps({self.identity: {'status': 'saved', 'notes': 'Follow up'}}))
        process_callback(self.data, TOKEN, '6789', self.query, api=self.api)
        first = load_tracking(self.data)[self.identity]
        self.assertEqual(first['status'], 'applied')
        self.assertEqual(first['notes'], 'Follow up')
        self.assertTrue(first['applied_at'])
        process_callback(self.data, TOKEN, '6789', self.query, api=self.api)
        self.assertEqual(load_tracking(self.data)[self.identity], first)
        self.assertEqual(self.calls[-1][1], 'editMessageReplyMarkup')
        self.assertEqual(self.calls[-1][2]['reply_markup']['inline_keyboard'], [])
        self.assertLessEqual(len(self.query['data'].encode()), 64)

    def test_foreign_user_and_foreign_chat_cannot_write(self):
        from applications.telegram import process_callback
        for query in (dict(self.query, **{'from': {'id': 1}}),
                      dict(self.query, message={'chat': {'id': 1, 'type': 'private'}}),
                      dict(self.query, data='applied:bad')):
            process_callback(self.data, TOKEN, '6789', query, api=self.api)
            self.assertFalse((self.data/'tracking.json').exists())

    def test_later_status_is_not_regressed(self):
        from applications.telegram import process_callback
        from applications.tracking import load_tracking
        previous = {'status': 'interviewing', 'notes': 'Tuesday', 'applied_at': 'original'}
        (self.data/'tracking.json').write_text(json.dumps({self.identity: previous}))
        process_callback(self.data, TOKEN, '6789', self.query, api=self.api)
        self.assertEqual(load_tracking(self.data)[self.identity], previous)

    def test_worker_offset_survives_restart_and_ui_failure(self):
        from applications.telegram import TelegramWorker
        from applications.tracking import load_tracking
        def api(token, method, payload):
            if method == 'getUpdates':
                return [{'update_id': 22, 'callback_query': self.query}]
            raise NetworkError('UI unavailable')
        worker = TelegramWorker(self.data, TOKEN, '6789', api=api)
        worker.tick()
        self.assertEqual(load_tracking(self.data)[self.identity]['status'], 'applied')
        self.assertEqual(TelegramWorker(self.data, TOKEN, '6789', api=api).offset, 23)

    def test_notifications_have_button(self):
        from applications.telegram import applied_callback
        reason = 'yes: role_family yes (0.90); level yes (0.90); responsibilities yes (0.90); qualifications yes (0.90)'
        job = {'identity': self.identity, 'is_listed': True, 'posted_at': NOW.isoformat(), 'assessment': reason}
        (self.data/'jobs.json').write_text(json.dumps({self.identity: job}))
        notify_telegram(self.data, TOKEN, '6789', api=self.api, now=NOW)
        button = self.calls[0][2]['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(button['text'], 'Mark applied')
        self.assertEqual(button['callback_data'], applied_callback(self.identity))

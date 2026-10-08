"""Telegram notifications; tokens never appear in errors or logs."""
import http.client
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request

from applications.http import NetworkError, ssl_context
from applications.proxy import NoRedirect
from applications.slack import notify_matches
from applications.storage import atomic_json, snapshot_lock


def validate_token(token):
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
        raise ValueError('Set a valid TELEGRAM_BOT_TOKEN from BotFather')


def request(token, method, payload):
    validate_token(token)
    if method not in {'sendMessage', 'getUpdates', 'answerCallbackQuery', 'editMessageReplyMarkup'}:
        raise ValueError('Unsupported Telegram operation')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl_context()))
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}',
                                 data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with opener.open(req, timeout=10) as response:
            body = response.read(1024 * 1024 + 1)
            if response.status != 200 or len(body) > 1024 * 1024:
                raise NetworkError('Telegram request failed')
            parsed = json.loads(body)
            if not isinstance(parsed, dict) or parsed.get('ok') is not True:
                raise NetworkError('Telegram did not acknowledge the request')
            return parsed.get('result')
    except urllib.error.HTTPError as error:
        messages = {
            401: 'Telegram rejected the bot token (HTTP 401). Copy the current token from BotFather.',
            404: 'Telegram bot endpoint was not found (HTTP 404). Check the bot token.',
            409: 'Telegram reports another update consumer or webhook (HTTP 409). Stop that consumer before looking up the chat ID.',
            429: 'Telegram rate limit reached (HTTP 429). Wait before retrying.',
        }
        raise NetworkError(messages.get(error.code, f'Telegram returned HTTP {error.code}.')) from None
    except TimeoutError:
        raise NetworkError('Telegram connection timed out. Check network access to api.telegram.org and retry.') from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, ssl.SSLError):
            detail = 'Telegram TLS connection failed. Check Python certificates and network TLS settings.'
        elif isinstance(error.reason, TimeoutError):
            detail = 'Telegram connection timed out. Check network access to api.telegram.org and retry.'
        else:
            detail = 'Cannot connect to Telegram. Check network access to api.telegram.org and retry.'
        raise NetworkError(detail) from None
    except (OSError, http.client.HTTPException):
        raise NetworkError('Telegram connection failed. Check your network and retry.') from None
    except ValueError:
        raise NetworkError('Telegram returned an invalid response. Retry later.') from None


def private_chat_ids(token, *, api=request):
    updates = api(token, 'getUpdates', {'timeout': 0, 'limit': 100, 'allowed_updates': ['message', 'callback_query']})
    return sorted({str(chat['id']) for update in updates
                   if (chat := update.get('message', {}).get('chat', {})).get('type') == 'private'})


def notify_telegram(data, token, chat_id, *, api=request, now=None, limit=20):
    if not token and not chat_id:
        return 0
    validate_token(token)
    # This integration is for one personal chat. Group limits differ.
    if not re.fullmatch(r'[1-9][0-9]*', chat_id):
        raise ValueError('Set TELEGRAM_CHAT_ID to your private chat ID')

    def send(_token, payload):
        api(token, 'sendMessage', {'chat_id': chat_id, 'text': payload['text'],
                                 'reply_markup': {'inline_keyboard': [[{
                                     'text': 'Mark applied', 'callback_data': applied_callback(payload['identity'])
                                 }]]},
                                 'link_preview_options': {'is_disabled': True}})

    return notify_matches(data, token, send=send, now=now, limit=limit,
                          state_name='telegram-notifications.json', validate=validate_token)


def applied_callback(identity):
    return 'applied:' + hashlib.sha256(identity.encode()).hexdigest()[:40]


def callback_feedback(api, token, method, payload):
    try:
        api(token, method, payload)
    except NetworkError:
        # An expired callback must not prevent the next update from being processed.
        print('Telegram button feedback unavailable; tracking state is retained.')


def process_callback(data, token, chat_id, query, *, api=request):
    from applications.listings import load_listings
    from applications.tracking import mark_applied
    message = query.get('message', {})
    chat = message.get('chat', {})
    if (str(query.get('from', {}).get('id')) != chat_id
            or str(chat.get('id')) != chat_id or chat.get('type') != 'private'):
        callback_feedback(api, token, 'answerCallbackQuery', {'callback_query_id': query['id'], 'text': 'This button is for the board owner.', 'show_alert': True})
        return
    identity = next((key for key in load_listings(data)
                     if applied_callback(key) == query.get('data')), None)
    if not identity:
        callback_feedback(api, token, 'answerCallbackQuery', {'callback_query_id': query['id'], 'text': 'Job not found.', 'show_alert': True})
        return
    result = mark_applied(data, identity)
    text = 'Marked applied.' if result['status'] == 'applied' else f"Already tracked as {result['status']}; no change."
    callback_feedback(api, token, 'answerCallbackQuery', {'callback_query_id': query['id'], 'text': text})
    callback_feedback(api, token, 'editMessageReplyMarkup', {'chat_id': chat_id, 'message_id': message['message_id'],
                                        'reply_markup': {'inline_keyboard': []}})


class TelegramWorker:
    def __init__(self, data, token, chat_id, *, api=request):
        import threading
        validate_token(token)
        if not re.fullmatch(r'[1-9][0-9]*', chat_id):
            raise ValueError('Set TELEGRAM_CHAT_ID to your private chat ID')
        self.data, self.token, self.chat_id, self.api = data, token, chat_id, api
        self.stop = threading.Event()
        self.path = data / 'telegram-updates.json'
        self.offset = json.loads(self.path.read_text()).get('offset', 0) if self.path.exists() else 0

    def tick(self):
        updates = self.api(self.token, 'getUpdates', {'offset': self.offset, 'timeout': 0,
                                                    'limit': 100, 'allowed_updates': ['callback_query']})
        for update in updates:
            if update['update_id'] < self.offset:
                continue
            if 'callback_query' in update:
                process_callback(self.data, self.token, self.chat_id, update['callback_query'], api=self.api)
            self.offset = update['update_id'] + 1
            with snapshot_lock(self.data):
                atomic_json(self.path, {'offset': self.offset})

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except (NetworkError, ValueError, OSError, KeyError, TypeError):
                print('Telegram button listener failed; retrying. Private details omitted.')
                self.stop.wait(30)
                continue
            self.stop.wait(3)

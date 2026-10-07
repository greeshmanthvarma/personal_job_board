"""Telegram notifications; tokens never appear in errors or logs."""
import http.client
import json
import re
import ssl
import urllib.error
import urllib.request

from applications.http import NetworkError, ssl_context
from applications.proxy import NoRedirect
from applications.slack import notify_matches


def validate_token(token):
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
        raise ValueError('Set a valid TELEGRAM_BOT_TOKEN from BotFather')


def request(token, method, payload):
    validate_token(token)
    if method not in {'sendMessage', 'getUpdates'}:
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
    updates = api(token, 'getUpdates', {'timeout': 0, 'limit': 100})
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
                                 'link_preview_options': {'is_disabled': True}})

    return notify_matches(data, token, send=send, now=now, limit=limit,
                          state_name='telegram-notifications.json', validate=validate_token)

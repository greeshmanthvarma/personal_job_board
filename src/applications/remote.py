"""Authenticated server-to-server board interface. Never serves the UI."""
import hmac
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from applications.listings import board_job_detail, board_page, list_board_jobs
from applications.tracking import update_tracking, export_tracking
from applications.runstate import load_run


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(10)
        super().__init__(*args, **kwargs)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise
    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()
    def handle_error(self, *_):
        pass  # Do not dump private exceptions into platform logs.


def make_remote_server(data: Path, token: str, port: int, host='0.0.0.0'):
    if len(token) < 32 or not token.isascii() or '\n' in token or '\r' in token:
        raise ValueError('BOARD_API_TOKEN must contain at least 32 ASCII characters')
    requests = deque()
    rate_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)
        def log_message(self, *_):
            pass
        def respond(self, status, payload, content_type='application/json; charset=utf-8'):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if status == 429:
                self.send_header('Retry-After', '60')
            if content_type.startswith('text/csv'):
                self.send_header('Content-Disposition', 'attachment; filename="job-tracking.csv"')
            self.end_headers()
            self.wfile.write(body)
        def error(self, status, code, message):
            self.respond(status, {'error': {'code': code, 'message': message}})
        def authorized(self):
            supplied = self.headers.get('Authorization', '').encode()
            if not hmac.compare_digest(supplied, f'Bearer {token}'.encode()):
                self.error(401, 'unauthorized', 'Authentication required')
                return False
            if 'Origin' in self.headers:
                self.error(403, 'browser_origin', 'Server-to-server requests only')
                return False
            with rate_lock:
                now = time.monotonic()
                while requests and requests[0] <= now-60:
                    requests.popleft()
                allowed = len(requests) < 120
                if allowed:
                    requests.append(now)
            if not allowed:
                self.error(429, 'rate_limited', 'Try again later')
            return allowed
        def do_GET(self):
            if self.path == '/healthz':
                return self.respond(200, {'ok': True})
            if not self.authorized():
                return
            try:
                parsed = urlsplit(self.path)
                if len(self.path) > 2048:
                    return self.error(400, 'invalid_request', 'Invalid request')
                if parsed.path == '/api/v1/jobs':
                    scan = load_run(data/'scan-state.json')
                    # Whitelist status metadata, never expose PID or raw diagnostics.
                    scan = {k: v for k,v in scan.items() if k in {'status','started_at','updated_at','processed_boards','target_boards','current_board'}}
                    scheduler = data/'scheduler-state.json'
                    if scheduler.exists():
                        scan['scheduler'] = json.loads(scheduler.read_text())
                    if parsed.query:
                        return self.respond(200, {**board_page(data, parsed.query), 'scan': scan})
                    jobs = list_board_jobs(data)
                    for job in jobs:
                        job.pop('fields', None)
                    return self.respond(200, {'jobs': jobs, 'scan': scan})
                if parsed.path == '/api/v1/jobs/detail':
                    return self.respond(200, board_job_detail(data, parsed.query))
                if parsed.path == '/api/v1/export' and not parsed.query:
                    return self.respond(200, export_tracking(data), 'text/csv; charset=utf-8')
                self.error(404, 'not_found', 'Not found')
            except LookupError:
                self.error(404, 'not_found', 'Unknown job')
            except ValueError as err:
                if str(err) == 'Invalid request':
                    return self.error(400, 'invalid_request', 'Invalid request')
                self.error(503, 'storage_unavailable', 'Stored data unavailable; no data was reset')
            except (TypeError, KeyError, OSError):
                self.error(503, 'storage_unavailable', 'Stored data unavailable; no data was reset')
        def do_POST(self):
            if not self.authorized():
                return
            if self.path != '/api/v1/tracking':
                return self.error(404, 'not_found', 'Not found')
            try:
                if self.headers.get('Content-Type','').split(';')[0] != 'application/json' or self.headers.get('Transfer-Encoding'):
                    raise ValueError()
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 32768:
                    raise ValueError()
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or set(body) != {'identity','status','notes'}:
                    raise ValueError()
                result = update_tracking(data, body['identity'], body['status'], body['notes'])
            except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                return self.error(400, 'invalid_tracking', 'Invalid tracking request')
            except OSError:
                return self.error(503, 'storage_unavailable', 'Save not confirmed')
            self.respond(200, result)
    return BoundedServer((host, port), Handler)

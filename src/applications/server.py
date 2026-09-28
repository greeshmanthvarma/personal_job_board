"""Loopback-only job board. No employer writes or arbitrary file serving."""
import json
import mimetypes
from urllib.parse import unquote, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from applications.listings import board_job_detail, board_page, list_board_jobs
from applications.tracking import update_tracking, export_tracking
from applications.runstate import load_run
from applications.board_view import BOARD_HTML

def static_asset(root: Path, request_path: str):
    path = unquote(urlsplit(request_path).path)
    if path == '/':
        candidate = root / 'index.html'
    elif path.startswith('/assets/') and '..' not in path.split('/') and '\\' not in path:
        candidate = root / path.lstrip('/')
    else:
        return None
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        return None
    return resolved.read_bytes(), mimetypes.guess_type(str(resolved))[0] or 'application/octet-stream'

def make_server(data: Path, port=8765, frontend_root: Path | None = None, remote_client=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log private notes or request payloads.
        def respond(self, status, payload, content_type='application/json; charset=utf-8', filename=None):
            body = payload if isinstance(payload,bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            if filename:
                self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)
        def allowed_host(self):
            return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
        def forward(self, path, payload=None):
            from applications.proxy import ProxyError
            try:
                status, body, content_type = remote_client.request(path, payload)
                return self.respond(status, body, content_type, 'job-tracking.csv' if path == '/api/export' else None)
            except ProxyError as err:
                return self.respond(err.status, {'error': {'code':'remote_unavailable','message':str(err)}})
        def do_GET(self):
            if not self.allowed_host():
                return self.respond(403,{'error':'Invalid host'})
            asset = static_asset(frontend_root, self.path) if frontend_root else None
            if asset:
                return self.respond(200, asset[0], asset[1])
            if self.path=='/':
                return self.respond(200,BOARD_HTML.encode(),'text/html; charset=utf-8')
            parsed = urlsplit(self.path)
            if len(self.path) > 2048:
                return self.respond(400, {'error': 'Invalid request'})
            if parsed.path == '/api/jobs':
                if remote_client:
                    return self.forward(self.path)
                if parsed.query:
                    try:
                        page = board_page(data, parsed.query)
                    except ValueError:
                        return self.respond(400, {'error': 'Invalid request'})
                    return self.respond(200, {**page, 'scan': load_run(data/'scan-state.json')})
                return self.respond(200, {'jobs': list_board_jobs(data), 'scan': load_run(data/'scan-state.json')})
            if parsed.path == '/api/jobs/detail' and not remote_client:
                try:
                    return self.respond(200, board_job_detail(data, parsed.query))
                except ValueError:
                    return self.respond(400, {'error': 'Invalid request'})
                except LookupError:
                    return self.respond(404, {'error': 'Unknown job'})
            if parsed.path == '/api/jobs/detail' and remote_client:
                return self.forward(self.path)
            if parsed.path == '/api/export' and not parsed.query:
                if remote_client:
                    return self.forward(self.path)
                return self.respond(200,export_tracking(data),'text/csv; charset=utf-8','job-tracking.csv')
            self.respond(404,{'error':'Not found'})
        def do_POST(self):
            expected=f'http://127.0.0.1:{self.server.server_port}'
            if not self.allowed_host() or self.headers.get('Origin')!=expected:
                return self.respond(403,{'error':'Same-origin requests required'})
            if self.path!='/api/tracking':
                return self.respond(404,{'error':'Not found'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                return self.respond(400,{'error':'JSON required'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=32768:
                    raise ValueError('Invalid request size')
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict) or set(body)!={'identity','status','notes'}:
                    raise ValueError('Invalid tracking fields')
                if remote_client:
                    return self.forward(self.path, body)
                value=update_tracking(data,body['identity'],body['status'],body['notes'])
            except (ValueError,TypeError,KeyError,UnicodeDecodeError) as err:
                return self.respond(400,{'error':str(err)})
            self.respond(200,value)
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)

def serve_board(data: Path, port=8765, remote_client=None):
    server=make_server(data,port,Path(__file__).resolve().parents[2] / 'frontend' / 'dist', remote_client)
    print(f'Private job board: http://127.0.0.1:{server.server_port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

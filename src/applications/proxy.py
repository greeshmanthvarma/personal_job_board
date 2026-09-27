"""Fixed HTTPS forwarding; credentials never reach browser code."""
import ipaddress
import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from applications.http import ssl_context

ROUTES = {'/api/jobs':'/api/v1/jobs', '/api/export':'/api/v1/export', '/api/tracking':'/api/v1/tracking'}
MAX_RESPONSE = 32*1024*1024

class ProxyError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None

def validate_origin(origin):
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment or parsed.port not in (None,443):
        raise ValueError('BOARD_REMOTE_URL must be an HTTPS origin without credentials or a path')
    host = parsed.hostname
    if '.' not in host or host.lower().endswith(('.localhost','.local','.internal')):
        raise ValueError('Remote hostname must be public')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError('Remote address must be public')
    return origin.rstrip('/'), host

class RemoteClient:
    def __init__(self, origin, token, opener=None, resolver=socket.getaddrinfo):
        self.origin, self.host = validate_origin(origin)
        if len(token)<32 or not token.isascii() or '\r' in token or '\n' in token:
            raise ValueError('BOARD_API_TOKEN must contain at least 32 ASCII characters')
        self.token = token
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPSHandler(context=ssl_context()))
        self.resolver = resolver
    def request(self, path, payload=None):
        if path not in ROUTES or (payload is not None) != (path == '/api/tracking'):
            raise ValueError('Unsupported forwarding operation')
        try:
            addresses = self.resolver(self.host,443,type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
                raise ProxyError(502, 'Remote destination is not public')
            headers = {'Authorization':f'Bearer {self.token}'}
            data = None
            if payload is not None:
                data=json.dumps(payload).encode();headers['Content-Type']='application/json'
            request=urllib.request.Request(self.origin+ROUTES[path],data=data,headers=headers)
            try:
                response=self.opener.open(request,timeout=15)
            except urllib.error.HTTPError as err:
                response=err
            with response:
                status=response.code
                if 300<=status<400:
                    raise ProxyError(502,'Remote redirects are not permitted')
                body=response.read(MAX_RESPONSE+1)
                if len(body)>MAX_RESPONSE:
                    raise ProxyError(502,'Remote response is too large')
                if not 200<=status<300:
                    raise ProxyError(502,'Remote request failed; save not confirmed' if payload else 'Remote request failed')
                return status,body,'text/csv; charset=utf-8' if path=='/api/export' else 'application/json; charset=utf-8'
        except (TimeoutError, socket.timeout) as err:
            raise ProxyError(504,'Remote request timed out; save may already have completed') from err
        except (urllib.error.URLError,OSError) as err:
            raise ProxyError(502,'Remote connection unavailable') from err

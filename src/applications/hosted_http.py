"""Allowlisted, bounded cloud reads. No redirects or environment proxies."""
import ipaddress
import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from applications.http import NetworkError, ssl_context, USER_AGENT
from applications.proxy import NoRedirect

ATS_HOSTS={'boards-api.greenhouse.io','api.ashbyhq.com','api.lever.co','api.eu.lever.co'}

def hosted_post(url, payload, headers, timeout=30):
    from applications.jev import ENDPOINT
    if url != ENDPOINT:raise NetworkError('Assessment destination rejected')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=ssl_context()))
    request=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','User-Agent':USER_AGENT,**headers},method='POST')
    try:
        try:response=opener.open(request,timeout=timeout)
        except urllib.error.HTTPError as error:response=error
        with response:
            if 300<=response.code<400:raise NetworkError('Assessment redirect rejected')
            body=response.read(32*1024*1024+1)
            if len(body)>32*1024*1024:raise NetworkError('Assessment response too large')
            return response.code,body
    except (urllib.error.URLError,OSError) as error:
        raise NetworkError('Assessment request failed') from error

def hosted_get(url, timeout=30):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ATS_HOSTS or parsed.username or parsed.password or parsed.port not in (None,443):
        raise NetworkError('ATS destination rejected')
    try:
        addresses=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise NetworkError('ATS destination rejected')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=ssl_context()))
        req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT})
        try:response=opener.open(req,timeout=timeout)
        except urllib.error.HTTPError as error:response=error
        with response:
            if 300<=response.code<400:raise NetworkError('ATS redirect rejected')
            body=response.read(32*1024*1024+1)
            if len(body)>32*1024*1024:raise NetworkError('ATS response too large')
            return response.code,body
    except (urllib.error.URLError,OSError) as err:
        raise NetworkError('ATS request failed') from err

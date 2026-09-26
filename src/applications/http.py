"""HTTP helpers. ATS reads stay at or above one second apart."""

import json
import random
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = "applications/0.1 (+https://greeshmanthvarma.vercel.app)"


class NetworkError(Exception):
    pass


def ssl_context() -> ssl.SSLContext:
    for candidate in (Path("/etc/ssl/cert.pem"), Path("/private/etc/ssl/cert.pem")):
        if candidate.exists():
            return ssl.create_default_context(cafile=str(candidate))
    return ssl.create_default_context()


@dataclass
class Limiter:
    sleep: callable
    monotonic: callable
    jitter: callable

    def __post_init__(self) -> None:
        self._last: float | None = None

    def wait(self) -> None:
        now = self.monotonic()
        if self._last is not None:
            delay = self._last + 1.0 + float(self.jitter()) - now
            if delay > 0:
                self.sleep(delay)
                now = self.monotonic()
        self._last = now


def production_limiter() -> Limiter:
    return Limiter(sleep=time.sleep, monotonic=time.monotonic, jitter=lambda: random.uniform(0, 0.2))


def get_bytes(url: str, timeout: float = 30) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()
    except urllib.error.URLError as err:
        raise NetworkError(str(err.reason)) from err


def post_json(url: str, payload: dict, headers: dict[str, str], timeout: float = 60) -> tuple[int, bytes]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()
    except urllib.error.URLError as err:
        raise NetworkError(str(err.reason)) from err


def paced_get(get, limiter: Limiter):
    def _get(url: str) -> tuple[int, bytes]:
        last_error: Exception | None = None
        status = 0
        body = b""
        for attempt in range(3):
            limiter.wait()
            try:
                status, body = get(url)
            except NetworkError as err:
                last_error = err
                continue
            if status in {429, 503} and attempt < 2:
                continue
            return status, body
        if last_error:
            raise last_error
        return status, body

    return _get

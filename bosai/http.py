"""Bounded HTTPS transport; no URLs, headers or response bodies in errors."""
import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class TransportError(Exception):
    def __init__(self, status=0, retryable=True, retry_after=0):
        self.status, self.retryable, self.retry_after = status, retryable, retry_after
        super().__init__(f'HTTP failure status={status} retryable={retryable}')


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Http:
    def __init__(self, timeout=15, sleep=time.sleep):
        self.timeout, self.sleep = timeout, sleep
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, url, payload=None, headers=None, attempts=1):
        hdr = {'User-Agent': 'BosaiMonitor/1.0 (JMA XML consumer)', **(headers or {})}
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        if body is not None:
            hdr['Content-Type'] = 'application/json'
        for attempt in range(attempts):
            try:
                req = urllib.request.Request(url, data=body, headers=hdr, method=method)
                try:
                    r = self.opener.open(req, timeout=self.timeout)
                except urllib.error.HTTPError as e:
                    r = e
                with r:
                    status = r.code
                    response = Response(status, r.read(16 * 1024 * 1024 + 1), {k.lower(): v for k, v in r.headers.items()})
                if len(response.body) > 16 * 1024 * 1024:
                    raise TransportError(0, False)
                if status in (200, 201, 202, 204, 304, 409):
                    return response
                retry_after = response.headers.get('retry-after', '0')
                raise TransportError(status, status == 429 or status >= 500,
                                     min(3600, int(retry_after)) if retry_after.isdigit() else 0)
            except (urllib.error.URLError, TimeoutError, OSError):
                error = TransportError()
            except TransportError as e:
                error = e
            if not error.retryable or attempt == attempts - 1:
                raise error from None
            self.sleep(min(30, max(error.retry_after, 2 ** attempt + random.random())))

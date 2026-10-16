"""POST a version record to the PatchingSite server, with retries."""
import time
from typing import Optional

import requests

TIMEOUT = 30
# 4xx answers that mean "try again later" rather than "this record is wrong"
RETRYABLE_4XX = (408, 429)


class PublishError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def _detail(resp) -> str:
    try:
        detail = resp.json().get('detail')
    except (ValueError, AttributeError):
        detail = None
    if detail is None:
        return resp.text[:200]
    if isinstance(detail, list):
        parts = []
        for d in detail:
            if isinstance(d, dict):
                loc = '.'.join(str(x) for x in d.get('loc', []))
                parts.append('%s: %s' % (loc, d.get('msg')) if loc else str(d.get('msg')))
            else:
                parts.append(str(d))
        return '; '.join(parts)
    return str(detail)


def post_record(record: dict, source: str, server_url: str, secret: str,
                attempts: int = 4, backoff: float = 2.0) -> int:
    """Post {**record, source} and return the server's revision.

    5xx, 408, 429, connection errors and timeouts are retried with exponential
    backoff (backoff * 2**(attempt-1) seconds); other 4xx and any redirect fail
    at once. Redirects are not followed, so the token never goes anywhere but
    server_url. The secret is only ever sent as a header and never put into an
    error message.
    """
    url = server_url.rstrip('/') + '/api/internal/records'
    body = {**record, 'source': source}
    last = 'no attempts made'
    status = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(backoff * 2 ** (attempt - 2))
        try:
            resp = requests.post(url, json=body, headers={'X-Internal-Token': secret},
                                 timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException as e:
            # Name the exception type only: its text may embed request details.
            status, last = None, 'request failed (%s)' % type(e).__name__
            continue
        status = resp.status_code
        if status == 200:
            try:
                return int(resp.json()['revision'])
            except (ValueError, KeyError, TypeError):
                raise PublishError('server returned 200 without a revision', status, False)
        if 300 <= status < 400:
            raise PublishError('server redirected (%d) to %s; redirects are not followed, fix'
                               ' PATCH_SERVER_URL' % (status, resp.headers.get('Location', '(no Location)')),
                               status, False)
        if 400 <= status < 500 and status not in RETRYABLE_4XX:
            raise PublishError('server rejected record (%d): %s' % (status, _detail(resp)),
                               status, False)
        last = 'server error (%d): %s' % (status, _detail(resp))
    raise PublishError('giving up after %d attempts: %s' % (attempts, last), status, True)

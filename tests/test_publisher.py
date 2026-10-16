import json
import socket

import pytest

from artifacts.publisher import PublishError, post_record
from tests.httpfake import FakeHttp

SECRET = 'S3CR3T-do-not-leak-7731'
RECORD = {k: 'v-' + k for k in (
    'package', 'version_name', 'version_code', 'sha256', 'size',
    'artifactory', 'supported', 'found_at', 'dex_md5', 'extra')}


def post(http, **kw):
    kw.setdefault('backoff', 0)
    return post_record(RECORD, 'whatsapp.com', http.base_url + '/', SECRET, **kw)


def test_post_sends_record_plus_source_and_token():
    snapshot = dict(RECORD)
    with FakeHttp() as http:
        http.post_responses = [(200, {'revision': 3})]
        post(http)
        (req,) = http.posts
    assert req['path'] == '/api/internal/records'
    assert req['headers']['x-internal-token'] == SECRET
    assert req['headers']['content-type'].startswith('application/json')
    body = json.loads(req['body'])
    assert body == {**snapshot, 'source': 'whatsapp.com'}
    assert len(body) == 11
    assert RECORD == snapshot and 'source' not in RECORD


def test_post_returns_revision():
    with FakeHttp() as http:
        http.post_responses = [(200, {'revision': 42})]
        assert post(http) == 42


def test_post_retries_5xx_then_succeeds():
    with FakeHttp() as http:
        http.post_responses = [(503, {}), (500, {}), (200, {'revision': 7})]
        assert post(http) == 7
        assert len(http.posts) == 3


def test_post_retries_5xx_then_gives_up():
    with FakeHttp() as http:
        http.post_responses = [(503, {'detail': 'down'})]
        with pytest.raises(PublishError) as ei:
            post(http, attempts=3)
        assert len(http.posts) == 3
    assert ei.value.retryable is True
    assert ei.value.status == 503


def test_connection_error_is_retryable():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(PublishError) as ei:
        post_record(RECORD, 'whatsapp.com', 'http://127.0.0.1:%d' % port, SECRET,
                    attempts=2, backoff=0)
    assert ei.value.retryable is True
    assert ei.value.status is None
    assert SECRET not in str(ei.value) and SECRET not in repr(ei.value)


@pytest.mark.parametrize('status,detail,expect', [
    (401, 'bad token', 'bad token'),
    (404, 'unknown package', 'unknown package'),
    (422, [{'loc': ['body', 'size'], 'msg': 'field required'}], 'field required'),
])
def test_4xx_is_not_retried(status, detail, expect):
    with FakeHttp() as http:
        http.post_responses = [(status, {'detail': detail})]
        with pytest.raises(PublishError) as ei:
            post(http)
        assert len(http.posts) == 1
    assert ei.value.retryable is False
    assert ei.value.status == status
    assert expect in str(ei.value)


def test_secret_not_in_errors():
    with FakeHttp() as http:
        http.post_responses = [(401, {'detail': 'bad token'})]
        with pytest.raises(PublishError) as ei:
            post(http)
        http.post_responses = [(500, {'detail': 'boom'})]
        with pytest.raises(PublishError) as ei2:
            post(http, attempts=2)
    for e in (ei.value, ei2.value):
        assert SECRET not in str(e) and SECRET not in repr(e)

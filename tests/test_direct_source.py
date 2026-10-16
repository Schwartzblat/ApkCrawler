import hashlib

import pytest
import requests

from artifacts.direct_source import NotAnApk, Probe, download, probe, unchanged
from artifacts.state import AppState
from httpfake import FakeHttp

LM = 'Mon, 01 Jan 2024 00:00:00 GMT'
APK = b'PK\x03\x04'  # every APK is a zip: it starts with a local file header


def st(etag=None, lm=None, length=None):
    return AppState(etag, lm, length, [], {})


def test_probe_reads_headers():
    with FakeHttp(body=b'12345', etag='"e1"', last_modified=LM) as http:
        assert probe(http.url) == Probe('"e1"', LM, 5)
        assert http.head_count == 1 and http.get_count == 0


def test_probe_missing_headers():
    with FakeHttp(body=b'') as http:
        assert probe(http.url) == Probe(None, None, 0)


def test_unchanged_etag_match():
    assert unchanged(Probe('"a"', None, 1), st(etag='"a"', length=99))


def test_unchanged_etag_differs():
    assert not unchanged(Probe('"b"', LM, 1), st(etag='"a"', lm=LM, length=1))


def test_unchanged_no_etag_lm_and_length():
    assert unchanged(Probe(None, LM, 5), st(lm=LM, length=5))
    assert not unchanged(Probe(None, LM, 6), st(lm=LM, length=5))
    assert not unchanged(Probe(None, 'other', 5), st(lm=LM, length=5))


def test_unchanged_no_etag_no_lm():
    assert not unchanged(Probe(None, None, 5), st(length=5))
    assert not unchanged(Probe(None, None, None), st())


def test_unchanged_probe_etag_but_state_none():
    assert not unchanged(Probe('"a"', LM, 5), st(lm=LM, length=5))


def test_download_writes_sha_named_file(tmp_path):
    body = APK + b'apk-bytes' * 1000
    sha = hashlib.sha256(body).hexdigest()
    dest = tmp_path / 'new' / 'apks'
    with FakeHttp(body=body, etag='"e"') as http:
        path, got_sha, _ = download(http.url, dest)
    assert got_sha == sha
    assert path == dest / (sha + '.apk')
    assert path.read_bytes() == body
    assert [p.name for p in dest.iterdir()] == [sha + '.apk']


def test_download_existing_file_replaced(tmp_path):
    body = APK + b'same'
    sha = hashlib.sha256(body).hexdigest()
    (tmp_path / (sha + '.apk')).write_bytes(body)
    with FakeHttp(body=body) as http:
        path, got_sha, _ = download(http.url, tmp_path)
    assert got_sha == sha and path.read_bytes() == body
    assert len(list(tmp_path.iterdir())) == 1


def test_download_returns_probe_from_get_headers(tmp_path):
    with FakeHttp(body=b'old', etag='"head"', last_modified='HEAD-LM') as http:
        http.get_body = APK + b'newer-bytes'
        http.get_etag = '"get"'
        http.get_last_modified = LM
        _, _, p = download(http.url, tmp_path)
    assert p == Probe('"get"', LM, len(APK + b'newer-bytes'))


def test_download_dropped_connection_leaves_nothing(tmp_path):
    with FakeHttp(body=APK + b'x' * 100000) as http:
        http.drop_after = 1000
        with pytest.raises(requests.RequestException):
            download(http.url, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_probe_and_download_ask_for_the_bytes_unencoded(tmp_path):
    with FakeHttp(body=APK + b'x') as http:
        probe(http.url)
        download(http.url, tmp_path)
    assert [r['method'] for r in http.requests] == ['HEAD', 'GET']
    assert all(r['headers'].get('accept-encoding') == 'identity' for r in http.requests)


@pytest.mark.parametrize('body', [b'<html>Checking your browser</html>', b'PK', b''])
def test_download_rejects_a_body_that_is_not_an_apk(tmp_path, body):
    with FakeHttp(body=body) as http:
        with pytest.raises(NotAnApk):
            download(http.url, tmp_path)
    assert list(tmp_path.iterdir()) == []

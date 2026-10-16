import os

import pytest

from artifacts import state
from artifacts.state import AppState, Kept

PKG = 'com.whatsapp'


def sample():
    return AppState(
        etag='"e1"', last_modified='Mon, 01 Jan 2024 00:00:00 GMT', length=123,
        kept=[Kept(apk_sha256='ab' * 32, path='/x/ab.apk', version_code=7,
                   downloaded_at='2026-10-17T00:00:00Z', processed_with='deadbeef',
                   posted=True, last_error=None)],
        alerted={'ab' * 32: '2026-10-17T01:00:00Z'})


def test_load_missing_is_empty(tmp_path):
    assert state.load(tmp_path, PKG) == AppState(None, None, None, [], {})


def test_save_load_round_trip(tmp_path):
    state.save(tmp_path, PKG, sample())
    assert (tmp_path / PKG / 'state.json').is_file()
    assert state.load(tmp_path, PKG) == sample()


def test_crash_before_replace_keeps_old_state(tmp_path, monkeypatch):
    state.save(tmp_path, PKG, sample())

    def boom(*a):
        raise OSError('crash')
    monkeypatch.setattr(os, 'replace', boom)
    new = sample()
    new.etag = '"e2"'
    with pytest.raises(OSError):
        state.save(tmp_path, PKG, new)
    monkeypatch.undo()
    assert state.load(tmp_path, PKG) == sample()

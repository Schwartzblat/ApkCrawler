"""The artifacts pipeline: new whatsapp.com APKs -> signature finders -> version records on the server."""
import fcntl
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests

from apps import AppConfig
from artifacts import alerts
from artifacts.direct_source import download, probe, unchanged
from artifacts.publisher import PublishError, post_record
from artifacts.runner import RunnerError, patcher_version, run_artifactory_only
from artifacts.state import AppState, Kept, load, save


RETRY_HINT = 'After fixing the cause, run the crawler with --pipeline artifacts --retry-failed.'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_new(app: AppConfig, artifacts_dir: Path, state: AppState) -> None:
    """Download the app's current APK when the probe says it changed. Network failures print and
    leave the state untouched, so the next run retries."""
    try:
        if unchanged(probe(app.direct_url), state):
            print(f'{app.name}: unchanged at {app.direct_url}')
            return
        print(f'{app.name}: new release, downloading')
        path, sha, got = download(app.direct_url, artifacts_dir / app.package_name / 'apks')
    except (requests.RequestException, OSError) as error:
        print(f'{app.name}: cannot fetch {app.direct_url} ({type(error).__name__}), will retry next run')
        return
    if not any(kept.apk_sha256 == sha for kept in state.kept):
        state.kept.append(Kept(apk_sha256=sha, path=str(path), version_code=0, downloaded_at=_now(),
                               processed_with=None, posted=False, last_error=None))
    # the headers of the GET that produced these bytes, not of the earlier HEAD
    state.etag, state.last_modified, state.length = got.etag, got.last_modified, got.length


def _process(app: AppConfig, patchers_dir: Path, server_url: str, secret: str, state: AppState,
             kept: Kept, current: str) -> None:
    sha = kept.apk_sha256
    try:
        record, supported = run_artifactory_only(patchers_dir, app, Path(kept.path))
    except RunnerError as error:
        kept.last_error, kept.processed_with = str(error), current
        alerts.once(state, f'run:{sha}:{current}', f'{app.name}: patcher {current} failed on {sha[:12]}',
                    f'{error}\n\n{RETRY_HINT}')
        return
    try:
        revision = post_record(record, app.direct_source, server_url, secret)
    except PublishError as error:
        kept.processed_with, kept.posted = current, False
        if error.retryable:
            kept.last_error = None  # finders run again next run; records are not cached
            print(f'{app.name}: server unavailable ({error}), will retry next run')
        else:
            kept.last_error = str(error)
            alerts.once(state, f'post:{sha}:{current}',
                        f'{app.name}: server rejected the record for {sha[:12]}', f'{error}\n\n{RETRY_HINT}')
        return
    kept.posted, kept.processed_with, kept.last_error = True, current, None
    kept.version_code = record.get('version_code', kept.version_code)
    version = record.get('version_name')
    features_off = record.get('features_off') or []
    print(f'{app.name} {version} ({kept.version_code}): posted, revision {revision},'
          f' supported={supported}, features_off={features_off}')
    if not supported or features_off:
        state_word = 'unsupported' if not supported else 'supported'
        alerts.once(state, f'record:{sha}:{current}',
                    f'{app.name} {version}: {state_word}, features off: {", ".join(features_off) or "none"}',
                    f'Patcher {current}, APK {sha}, revision {revision}.')


def _prune(state: AppState, keep: int) -> None:
    state.kept.sort(key=lambda k: k.downloaded_at, reverse=True)
    for old in state.kept[keep:]:
        try:
            os.unlink(old.path)
        except FileNotFoundError:
            pass
    del state.kept[keep:]


def _run_app(app: AppConfig, patchers_dir: Path, artifacts_dir: Path, server_url: str, secret: str,
             keep: int, retry_failed: bool) -> None:
    try:
        current = patcher_version(patchers_dir, app.patcher_name)
    except RunnerError as error:
        print(f'{app.name}: {error}')
        return
    state = load(artifacts_dir, app.package_name)
    if retry_failed:
        for kept in state.kept:
            kept.last_error = None  # parked by a 4xx or a crash: try again on this run
    _fetch_new(app, artifacts_dir, state)
    _prune(state, keep)
    save(artifacts_dir, app.package_name, state)
    for kept in sorted(state.kept, key=lambda k: k.downloaded_at, reverse=True):
        if kept.processed_with != current or (not kept.posted and kept.last_error is None):
            _process(app, patchers_dir, server_url, secret, state, kept, current)
            save(artifacts_dir, app.package_name, state)


def run(apps: Iterable[AppConfig], patchers_dir: Path, artifacts_dir: Path, server_url: str, secret: str,
        keep: int = 3, retry_failed: bool = False) -> None:
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    with open(artifacts_dir / '.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another artifacts run holds the lock, exiting')
            return
        for app in apps:
            if 'artifacts' in app.pipelines and app.direct_url:
                _run_app(app, Path(patchers_dir), artifacts_dir, server_url, secret, keep, retry_failed)

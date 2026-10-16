import dataclasses
import fcntl
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

import crawler as crawler_module
from apps import AppConfig
from artifacts import pipeline
from artifacts.state import load
from fakepatcher import SAMPLE_RECORD, calls, make_fake_patcher, set_behavior, set_version
from httpfake import FakeHttp

OK = (200, {'revision': 7})
DEAD_URL = 'http://127.0.0.1:1/app.apk'  # nothing listens there
T0 = datetime(2026, 10, 17, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    artifacts_dir = tmp_path / 'artifacts'
    monkeypatch.setenv('ARTIFACTS_DIR', str(artifacts_dir))
    for name in ('ALERT_EMAIL_TO', 'SMTP_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    patcher = make_fake_patcher(tmp_path / 'patchers', 'FakePatcher')
    with FakeHttp(body=b'apk-one', etag='"E1"') as http:
        http.post_responses = [OK]
        app = AppConfig(name='Fake', package_name='com.fake', patcher_name='FakePatcher',
                        pipelines=frozenset({'artifacts'}), direct_url=http.url, direct_source='fake.test')

        class Env:
            pass

        e = Env()
        e.http, e.app, e.patcher, e.dir = http, app, patcher, artifacts_dir
        e.run = lambda keep=3: pipeline.run([app], tmp_path / 'patchers', artifacts_dir,
                                            http.base_url, 'sekret', keep=keep)
        e.state = lambda: load(artifacts_dir, 'com.fake')
        e.alerts = lambda: (artifacts_dir / 'alerts.log').read_text().splitlines() \
            if (artifacts_dir / 'alerts.log').exists() else []
        yield e


@pytest.fixture
def clock(monkeypatch):
    """The pipeline's clock, starting at T0; advance it with clock.advance(minutes=...)."""
    class Clock:
        now = T0

        def advance(self, **delta):
            self.now += timedelta(**delta)
    c = Clock()
    monkeypatch.setattr(pipeline, '_now', lambda: c.now)
    return c


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr('artifacts.publisher.time.sleep', lambda s: None)


def test_new_apk_is_processed_and_posted(env):
    env.run()
    assert len(calls(env.patcher)) == 1
    [post] = env.http.posts
    assert post['path'] == '/api/internal/records'
    assert post['headers']['x-internal-token'] == 'sekret'
    assert json.loads(post['body'])['source'] == 'fake.test'
    state = env.state()
    [kept] = state.kept
    assert (kept.posted, kept.processed_with, kept.version_code, kept.last_error) == (True, '3.0.0', 1, None)
    assert state.etag == '"E1"'
    assert (env.dir / 'com.fake' / 'apks' / (kept.apk_sha256 + '.apk')).read_bytes() == b'apk-one'


def test_unchanged_probe_does_nothing(env):
    env.run()
    env.run()
    assert env.http.get_count == 1 and env.http.head_count == 2
    assert len(calls(env.patcher)) == 1 and len(env.http.posts) == 1


def test_same_bytes_new_etag_not_reprocessed(env):
    env.run()
    env.http.etag = '"E2"'
    env.run()
    assert env.http.get_count == 2
    assert len(calls(env.patcher)) == 1 and len(env.http.posts) == 1
    state = env.state()
    assert len(state.kept) == 1 and state.etag == '"E2"'
    assert (env.dir / 'com.fake' / 'apks' / (state.kept[0].apk_sha256 + '.apk')).exists()


def test_state_follows_downloaded_bytes(env):
    import hashlib
    env.http.get_body = b'different bytes'
    env.http.get_etag = '"E2"'
    env.http.get_length = None
    env.run()
    state = env.state()
    assert state.kept[0].apk_sha256 == hashlib.sha256(b'different bytes').hexdigest()
    assert state.etag == '"E2"'


def test_unsupported_record_alerts_once(env):
    set_behavior(env.patcher, exit=3, record={**SAMPLE_RECORD, 'supported': False, 'features_off': ['ads']})
    env.run()
    assert len(env.http.posts) == 1
    assert len(env.alerts()) == 1 and '2.25.1.1' in env.alerts()[0] and 'ads' in env.alerts()[0]
    env.http.etag = '"E2"'
    env.http.body = b'apk-two'
    env.run()
    assert len(env.alerts()) == 2  # the second APK is a different record
    env.run()
    assert len(env.alerts()) == 2


def test_features_off_on_supported_record_alerts(env):
    set_behavior(env.patcher, record={**SAMPLE_RECORD, 'features_off': ['premium']})
    env.run()
    assert len(env.alerts()) == 1 and 'premium' in env.alerts()[0]


def test_patcher_crash_alerts_and_keeps_apk(env):
    set_behavior(env.patcher, exit=1, record=None, print_lines=['boom'])
    env.run()
    kept = env.state().kept[0]
    assert kept.last_error and kept.processed_with == '3.0.0' and not kept.posted
    assert len(env.alerts()) == 1 and not env.http.posts
    env.run()
    assert len(calls(env.patcher)) == 1 and len(env.alerts()) == 1
    set_version(env.patcher, '3.1.0')
    set_behavior(env.patcher, record=SAMPLE_RECORD)
    env.run()
    assert len(calls(env.patcher)) == 2
    kept = env.state().kept[0]
    assert kept.posted and kept.last_error is None and kept.processed_with == '3.1.0'


def test_422_alerts_once(env):
    env.http.post_responses = [(422, {'detail': 'bad record'})]
    env.run()
    kept = env.state().kept[0]
    assert not kept.posted and kept.last_error and kept.processed_with == '3.0.0'
    assert len(env.alerts()) == 1
    env.run()
    assert len(env.http.posts) == 1 and len(env.alerts()) == 1


def test_server_down_retried_next_run(env, monkeypatch):
    monkeypatch.setattr('artifacts.publisher.time.sleep', lambda s: None)
    env.http.post_responses = [(503, {'detail': 'down'})]
    env.run()
    kept = env.state().kept[0]
    assert not kept.posted and kept.last_error is None and kept.processed_with == '3.0.0'
    assert not env.alerts()
    attempts = len(env.http.posts)
    env.http.post_responses = [OK]
    env.run()
    assert len(calls(env.patcher)) == 2 and len(env.http.posts) == attempts + 1
    assert env.state().kept[0].posted


def test_probe_failure_falls_through_to_kept(env, capsys):
    env.run()
    set_version(env.patcher, '3.1.0')
    env.app.direct_url = 'http://127.0.0.1:1/app.apk'  # nothing listens there
    env.run()
    assert 'will retry next run' in capsys.readouterr().out
    state = env.state()
    assert state.etag == '"E1"' and state.kept[0].processed_with == '3.1.0'
    assert not env.alerts()


def test_patcher_version_change_reprocesses_kept_apks(env):
    for body, etag in ((b'a', '"1"'), (b'b', '"2"')):
        env.http.body, env.http.etag = body, etag
        env.run()
    set_version(env.patcher, '4.0.0')
    env.http.post_responses = [OK]
    before = len(env.http.posts)
    env.run()
    state = env.state()
    assert len(env.http.posts) == before + 2
    assert all(k.posted and k.processed_with == '4.0.0' for k in state.kept)
    newest_first = [c['argv'][3] for c in calls(env.patcher)[-2:]]
    assert newest_first == [k.path for k in sorted(state.kept, key=lambda k: k.downloaded_at, reverse=True)]
    env.run()
    assert len(env.http.posts) == before + 2


def test_keeps_only_newest_three(env):
    import hashlib
    shas = [hashlib.sha256(b'apk%d' % i).hexdigest() for i in range(5)]
    for i in range(5):
        env.http.body, env.http.etag = b'apk%d' % i, '"%d"' % i
        env.run()
    state = env.state()
    assert {k.apk_sha256 for k in state.kept} == set(shas[2:])
    apks = env.dir / 'com.fake' / 'apks'
    assert sorted(p.name for p in apks.iterdir()) == sorted(s + '.apk' for s in shas[2:])
    assert not (apks / (shas[0] + '.apk')).exists()
    assert len(env.http.posts) == 5  # every new release processed and posted once


def test_parked_4xx_retried_only_with_retry_failed(env):
    env.http.post_responses = [(401, {'detail': 'bad token'})]
    env.run()
    assert len(env.http.posts) == 1
    assert '--retry-failed' in env.alerts()[0]
    env.http.post_responses = [OK]
    env.run()
    assert len(env.http.posts) == 1
    pipeline.run([env.app], env.patcher.parent, env.dir, env.http.base_url, 'sekret', retry_failed=True)
    assert len(env.http.posts) == 2
    kept = env.state().kept[0]
    assert kept.posted and kept.last_error is None


def test_crash_alert_mentions_retry_flag(env):
    set_behavior(env.patcher, exit=1, record=None)
    env.run()
    assert '--retry-failed' in env.alerts()[0]


def test_second_run_exits_when_locked(env, capsys):
    env.dir.mkdir(parents=True)
    with open(env.dir / '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        env.run()
    assert env.http.head_count == 0 and env.http.get_count == 0 and not calls(env.patcher)
    assert 'lock' in capsys.readouterr().out


# --- failures that persist: one alert after an hour, cleared by recovery ---

def test_fetch_failing_for_an_hour_alerts_once(env, clock):
    env.app.direct_url = DEAD_URL
    env.run()
    assert env.state().failing == {'fetch': T0.isoformat()}
    clock.advance(minutes=59)
    env.run()
    assert not env.alerts()
    clock.advance(minutes=1)
    env.run()
    [alert] = env.alerts()
    assert 'Fake' in alert and 'fetch' in alert
    assert 'ConnectionError' in alert and T0.isoformat() in alert  # the last error and the first failure
    clock.advance(minutes=15)
    env.run()
    assert len(env.alerts()) == 1


def test_fetch_recovery_clears_the_streak_and_a_new_outage_alerts_again(env, clock):
    env.app.direct_url = DEAD_URL
    env.run()
    clock.advance(hours=1)
    env.run()
    assert len(env.alerts()) == 1
    env.app.direct_url = env.http.url
    env.run()
    state = env.state()
    assert state.failing == {} and 'failing:fetch' not in state.alerted
    assert state.kept[0].posted
    env.app.direct_url = DEAD_URL
    clock.advance(minutes=15)
    env.run()
    clock.advance(minutes=59)
    env.run()
    assert len(env.alerts()) == 1
    clock.advance(minutes=1)
    env.run()
    assert len(env.alerts()) == 2


def test_download_failure_is_a_fetch_failure(env, clock):
    env.http.drop_after = 3
    env.run()
    state = env.state()
    assert 'fetch' in state.failing and not state.kept and state.etag is None
    clock.advance(hours=1)
    env.run()
    assert len(env.alerts()) == 1


def test_server_unavailable_for_an_hour_alerts_once(env, clock, no_backoff):
    env.http.post_responses = [(503, {'detail': 'Not configured'})]
    env.run()
    sha = env.state().kept[0].apk_sha256
    assert env.state().failing == {f'post:{sha}': T0.isoformat()}
    clock.advance(minutes=59)
    env.run()
    assert not env.alerts()
    clock.advance(minutes=1)
    env.run()
    [alert] = env.alerts()
    assert 'Fake' in alert and sha[:12] in alert and 'Not configured' in alert
    clock.advance(minutes=15)
    env.run()
    assert len(env.alerts()) == 1
    env.http.post_responses = [OK]
    env.run()
    state = env.state()
    assert state.kept[0].posted
    assert state.failing == {} and f'failing:post:{sha}' not in state.alerted


def test_unreadable_patcher_version_alerts_after_an_hour(env, clock, capsys):
    (env.patcher / 'constants.py').unlink()
    env.run()
    assert 'constants.py' in capsys.readouterr().out
    assert env.http.head_count == 0 and 'patcher_version' in env.state().failing
    clock.advance(hours=1)
    env.run()
    [alert] = env.alerts()
    assert 'Fake' in alert and 'PATCHER_VERSION' in alert
    clock.advance(minutes=15)
    env.run()
    assert len(env.alerts()) == 1
    set_version(env.patcher, '3.0.0')
    env.run()
    state = env.state()
    assert state.failing == {} and 'failing:patcher_version' not in state.alerted
    assert state.kept[0].posted


def test_unexpected_error_alerts_once_per_error_and_other_apps_still_run(env, capsys):
    other = dataclasses.replace(env.app, name='Other', package_name='com.other')
    broken = env.dir / 'com.fake' / 'state.json'
    marker = env.dir / 'com.fake' / 'last_crash.txt'
    broken.parent.mkdir(parents=True)
    broken.write_text('{not json')

    def run():
        pipeline.run([env.app, other], env.patcher.parent, env.dir, env.http.base_url, 'sekret')
    run()
    assert 'Traceback' in capsys.readouterr().out
    [alert] = env.alerts()
    assert 'Fake' in alert and 'JSONDecodeError' in alert
    assert load(env.dir, 'com.other').kept[0].posted  # the next app still ran
    run()
    assert len(env.alerts()) == 1
    broken.write_text('[]')  # a different error alerts again
    run()
    assert len(env.alerts()) == 2 and 'AttributeError' in env.alerts()[1]
    broken.unlink()
    run()
    assert not marker.exists() and env.state().kept[0].posted  # a clean pass forgets the crash
    broken.write_text('[]')
    run()
    assert len(env.alerts()) == 3


def test_crash_alert_never_contains_the_secret(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('token sekret leaked')
    monkeypatch.setattr(pipeline, 'post_record', boom)
    env.run()
    out = '\n'.join(env.alerts()) + (env.dir / 'com.fake' / 'last_crash.txt').read_text()
    assert 'RuntimeError' in out and 'sekret' not in out


# --- crawler.main wiring ---

@pytest.fixture
def wired(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(crawler_module, 'run_over_crawlers', lambda **kw: seen.append(('build', kw)))
    monkeypatch.setattr(crawler_module, 'check_patchers', lambda apps, need_paywall=True: seen.append(('check', [a.package_name for a in apps], need_paywall)))
    monkeypatch.setattr(pipeline, 'run', lambda *a, **kw: seen.append(('artifacts', a, kw)))
    monkeypatch.setenv('PATCHERS_DIR', str(tmp_path / 'p'))
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path / 'art'))
    for name in ('PATCH_SERVER_URL', 'CRAWLER_SECRET'):
        monkeypatch.delenv(name, raising=False)

    def call(*argv):
        monkeypatch.setattr(sys, 'argv', ['crawler.py', *argv])
        crawler_module.main()
        return seen
    return call


def test_main_default_runs_only_build(wired):
    seen = wired()
    assert [s[0] for s in seen] == ['check', 'build']


def test_main_artifacts_runs_only_artifacts(wired, monkeypatch, tmp_path):
    monkeypatch.setenv('PATCH_SERVER_URL', 'http://srv')
    monkeypatch.setenv('CRAWLER_SECRET', 's')
    seen = wired('--pipeline', 'artifacts')
    assert [s[0] for s in seen] == ['check', 'artifacts']
    assert seen[0][2] is False
    _, args, _ = seen[1]
    apps, patchers_dir, artifacts_dir, url, secret = args
    assert [a.package_name for a in apps] == ['com.whatsapp']
    assert patchers_dir == tmp_path / 'p' and artifacts_dir == tmp_path / 'art'
    assert (url, secret) == ('http://srv', 's')


def test_main_all_runs_both_and_dedupes_apps(wired, monkeypatch):
    monkeypatch.setenv('PATCH_SERVER_URL', 'http://srv')
    monkeypatch.setenv('CRAWLER_SECRET', 's')
    seen = wired('--pipeline', 'all')
    assert [s[0] for s in seen] == ['check', 'build', 'artifacts']
    assert seen[0][1].count('com.whatsapp') == 1


@pytest.mark.parametrize('missing', ['PATCH_SERVER_URL', 'CRAWLER_SECRET'])
def test_main_artifacts_requires_env(wired, monkeypatch, missing, capsys):
    for name in ('PATCH_SERVER_URL', 'CRAWLER_SECRET'):
        if name != missing:
            monkeypatch.setenv(name, 'value-not-to-print')
    with pytest.raises(SystemExit):
        wired('--pipeline', 'artifacts')
    err = capsys.readouterr().err
    assert missing in err and 'value-not-to-print' not in err


@pytest.mark.parametrize('url', ['androidmod.site', 'ftp://androidmod.site', '//androidmod.site'])
def test_main_artifacts_requires_an_http_server_url(wired, monkeypatch, capsys, url):
    monkeypatch.setenv('PATCH_SERVER_URL', url)
    monkeypatch.setenv('CRAWLER_SECRET', 's')
    with pytest.raises(SystemExit):
        wired('--pipeline', 'artifacts')
    err = capsys.readouterr().err
    assert 'PATCH_SERVER_URL' in err and 'androidmod.site' not in err


def test_main_accepts_https_server_url(wired, monkeypatch):
    monkeypatch.setenv('PATCH_SERVER_URL', 'HTTPS://androidmod.site')
    monkeypatch.setenv('CRAWLER_SECRET', 's')
    assert [s[0] for s in wired('--pipeline', 'artifacts')] == ['check', 'artifacts']


def test_retry_failed_flag_parses():
    assert crawler_module.build_parser().parse_args(['--retry-failed']).retry_failed is True
    assert crawler_module.build_parser().parse_args([]).retry_failed is False


def test_main_passes_retry_failed(wired, monkeypatch):
    monkeypatch.setenv('PATCH_SERVER_URL', 'http://srv')
    monkeypatch.setenv('CRAWLER_SECRET', 's')
    seen = wired('--pipeline', 'artifacts', '--retry-failed')
    assert seen[-1][2] == {'retry_failed': True}

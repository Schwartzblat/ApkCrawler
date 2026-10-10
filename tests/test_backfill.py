import sys
import zipfile

import pytest
from packaging.version import Version

import crawler as crawler_module
from apps import AppConfig
from crawler import versions_to_fetch

APP = AppConfig(name='12+', package_name='com.keshet.mako.VOD')  # no patcher: downloaded only


def versions(*names):
    return {Version(name) for name in names}


def fake_crawler(name, offered, *, arch='arm64-v8a', fails=False):
    """A source offering `offered` versions; records how it was asked and what it downloaded."""
    class Fake:
        listed = []
        downloaded = []

        @staticmethod
        def get_available_versions(app, count=None):
            Fake.listed.append(count)
            return {version: Version(version) for version in offered}

        @staticmethod
        def download_specific_version(output_path, app, version):
            Fake.downloaded.append(str(version))
            if fails:
                raise RuntimeError('download broke')
            path = output_path / f'{app.package_name}-{version}.apk'
            with zipfile.ZipFile(path, 'w') as apk:
                apk.writestr(f'lib/{arch}/libapp.so', b'')
            return path

    Fake.name = name
    return Fake


@pytest.fixture
def apps_path(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler_module, 'APPS_PATH', tmp_path)
    monkeypatch.setattr(crawler_module, 'APPS', [APP])
    return tmp_path


def make_local(apps_path, *names):
    for name in names:
        (apps_path / APP.package_name / name).mkdir(parents=True)


def on_disk(apps_path):
    return sorted((p.name for p in (apps_path / APP.package_name).iterdir()), key=Version)


def test_without_backfill_only_newer_releases_are_fetched():
    local, available = versions('41.0', '43.0'), versions('40.0', '42.0', '43.0', '44.0', '45.0')
    assert versions_to_fetch(local, available, 0) == [Version('44.0'), Version('45.0')]


def test_backfill_fills_the_gaps_among_the_newest_releases():
    # newest 4 of everything known are 45, 44, 43, 42; 43 is local, 40 is too old
    local, available = versions('41.0', '43.0'), versions('40.0', '42.0', '43.0', '44.0', '45.0')
    assert versions_to_fetch(local, available, 4) == [Version('42.0'), Version('44.0'), Version('45.0')]


def test_backfill_still_fetches_every_new_release():
    assert versions_to_fetch(versions('40.0'), versions('41.0', '42.0', '43.0'), 1) == [
        Version('41.0'), Version('42.0'), Version('43.0')]


def test_backfill_downloads_each_missing_release_from_the_first_source_that_lists_it(apps_path, monkeypatch):
    make_local(apps_path, '43.0')
    play = fake_crawler('Play', ['43.0', '42.0'])
    mirror = fake_crawler('Mirror', ['43.0', '42.0', '41.0', '40.0'])
    monkeypatch.setattr(crawler_module, 'crawlers', [play, mirror])
    crawler_module.run_over_crawlers(backfill=3)
    assert (play.listed, mirror.listed) == ([3], [3])
    assert (play.downloaded, mirror.downloaded) == (['42.0'], ['41.0'])
    assert on_disk(apps_path) == ['41.0', '42.0', '43.0']


def test_without_backfill_sources_give_their_usual_list(apps_path, monkeypatch):
    make_local(apps_path, '43.0')
    play = fake_crawler('Play', ['44.0'])
    monkeypatch.setattr(crawler_module, 'crawlers', [play])
    crawler_module.run_over_crawlers()
    assert play.listed == [None]
    assert on_disk(apps_path) == ['43.0', '44.0']


def test_a_failed_download_falls_back_to_the_next_source(apps_path, monkeypatch):
    play = fake_crawler('Play', ['44.0'], fails=True)
    mirror = fake_crawler('Mirror', ['44.0'])
    monkeypatch.setattr(crawler_module, 'crawlers', [play, mirror])
    crawler_module.run_over_crawlers()
    assert (play.downloaded, mirror.downloaded) == (['44.0'], ['44.0'])
    assert [p.name for p in (apps_path / APP.package_name / '44.0').iterdir()] == ['com.keshet.mako.VOD-44.0.apk']


def test_a_build_without_arm64_falls_back_to_the_next_source(apps_path, monkeypatch):
    play = fake_crawler('Play', ['44.0'], arch='x86_64')
    mirror = fake_crawler('Mirror', ['44.0'])
    monkeypatch.setattr(crawler_module, 'crawlers', [play, mirror])
    crawler_module.run_over_crawlers()
    assert mirror.downloaded == ['44.0']
    assert on_disk(apps_path) == ['44.0']


def test_a_version_no_source_can_deliver_leaves_nothing_behind(apps_path, monkeypatch):
    monkeypatch.setattr(crawler_module, 'crawlers', [fake_crawler('Play', ['44.0'], fails=True)])
    crawler_module.run_over_crawlers()
    assert on_disk(apps_path) == []


def test_backfill_flag_reaches_the_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(crawler_module, 'run_over_crawlers', lambda remote=None, backfill=0: seen.update(
        remote=remote, backfill=backfill))
    monkeypatch.setattr(crawler_module, 'check_patchers', lambda apps: None)
    monkeypatch.setattr(sys, 'argv', ['crawler.py', '--backfill', '5'])
    crawler_module.main()
    assert seen == {'remote': None, 'backfill': 5}


@pytest.mark.parametrize('value', ['0', '-1', 'all'])
def test_backfill_needs_a_positive_count(monkeypatch, value):
    monkeypatch.setattr(sys, 'argv', ['crawler.py', '--backfill', value])
    with pytest.raises(SystemExit) as excinfo:
        crawler_module.main()
    assert excinfo.value.code == 2

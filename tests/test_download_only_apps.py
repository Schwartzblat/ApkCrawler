import zipfile

import pytest
from packaging.version import Version

import crawler as crawler_module
from apps import AppConfig
from crawlers import apkmirror_downloader, apkpure_downloader
from crawlers.apkmirror_downloader import APKMirrorCrawler
from crawlers.apkpure_downloader import APKPureCrawler
from crawlers.play_downloader import PlayCrawler

OKCUPID = AppConfig(name='OkCupid', package_name='com.okcupid.okcupid')


class FakeCrawler:
    name = 'Fake'

    @staticmethod
    def get_available_versions(app):
        return {'116.0.0': Version('116.0.0')}

    @staticmethod
    def download_specific_version(output_path, app, version):
        path = output_path / f'{app.package_name}-{version}.apk'
        with zipfile.ZipFile(path, 'w') as apk:
            apk.writestr('lib/arm64-v8a/libapp.so', b'')
        return path


def test_app_without_patcher_is_downloaded_but_not_patched(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler_module, 'APPS_PATH', tmp_path)
    monkeypatch.setattr(crawler_module, 'crawlers', [FakeCrawler])
    monkeypatch.setattr(crawler_module, 'APPS', [OKCUPID])
    monkeypatch.setattr(crawler_module, 'patch_app', lambda *args: pytest.fail('patch_app must not run'))
    crawler_module.run_over_crawlers()
    assert (tmp_path / 'com.okcupid.okcupid' / '116.0.0' / 'com.okcupid.okcupid-116.0.0.apk').exists()


def test_apkmirror_skips_apps_it_has_no_config_for(monkeypatch):
    monkeypatch.setattr(apkmirror_downloader, 'CloudflareSession', lambda: pytest.fail('no request expected'))
    assert APKMirrorCrawler.get_available_versions(OKCUPID) == {}


def test_apkpure_skips_apps_it_has_no_config_for(monkeypatch):
    monkeypatch.setattr(apkpure_downloader.requests, 'get', lambda *a, **k: pytest.fail('no request expected'))
    assert APKPureCrawler.get_available_versions(OKCUPID) == {}


def test_play_is_tried_first():
    assert crawler_module.crawlers[0] is PlayCrawler

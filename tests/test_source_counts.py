import pytest
from packaging.version import Version

from apps import AppConfig
from crawlers import apkmirror_downloader, apkpure_downloader
from crawlers.apkmirror_downloader import APKMirrorCrawler
from crawlers.apkpure_downloader import APKPureCrawler

MIRRORED = AppConfig(
    name='App', package_name='com.example.app', apkmirror_app_id='app',
    apkmirror_url_template='/apk/x/app/app-{}-release/', apkpure_app_path='app/com.example.app',
)
NAMES = ['46.0', '45.0', '44.0', '43.0', '42.0', '41.0', '40.0']  # newest first, as both sites list them


class Page:
    def __init__(self, text):
        self.text = text


@pytest.fixture
def sites(monkeypatch):
    apkpure = ''.join(f'"{name}"\n    data-dt-versioncode="{i}"\n' for i, name in enumerate(NAMES))
    apkmirror = ''.join(f'<a href="/apk/x/app/app-{name.replace(".", "-")}-release/">App {name}</a>\n'
                        for name in NAMES)
    monkeypatch.setattr(apkpure_downloader.requests, 'get', lambda *args, **kwargs: Page(apkpure))

    class Session:
        def get(self, url):
            return Page(apkmirror)

    monkeypatch.setattr(apkmirror_downloader, 'CloudflareSession', Session)


def newest_first(available):
    return sorted(available.values(), reverse=True)


@pytest.mark.parametrize('source', [APKPureCrawler, APKMirrorCrawler])
def test_mirrors_list_their_five_newest_releases_by_default(sites, source):
    assert newest_first(source.get_available_versions(MIRRORED)) == [Version(name) for name in NAMES[:5]]


@pytest.mark.parametrize('source', [APKPureCrawler, APKMirrorCrawler])
@pytest.mark.parametrize('count', [2, 7])
def test_mirrors_list_as_many_releases_as_asked_for(sites, source, count):
    assert newest_first(source.get_available_versions(MIRRORED, count)) == [Version(name) for name in NAMES[:count]]

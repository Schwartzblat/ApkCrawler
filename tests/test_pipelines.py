import pytest
from packaging.version import Version

import crawler as crawler_module
from apps import APPS, AppConfig
from crawler import apps_in, build_parser, check_patchers

BUILD_APP = AppConfig(name='Build', package_name='com.example.build')
ARTIFACTS_APP = AppConfig(name='Artifacts', package_name='com.example.artifacts', pipelines=frozenset({'artifacts'}))


def fake_crawler(fetched):
    class Fake:
        name = 'fake'

        @staticmethod
        def get_available_versions(app, count=None):
            fetched.append(app.package_name)
            return {}

    return Fake


def test_build_pipeline_unchanged_by_default(tmp_path, monkeypatch):
    fetched = []
    monkeypatch.setattr(crawler_module, 'APPS_PATH', tmp_path)
    monkeypatch.setattr(crawler_module, 'crawlers', [fake_crawler(fetched)])
    crawler_module.run_over_crawlers()
    assert fetched == [app.package_name for app in APPS]
    assert all(app.pipelines == {'build'} or app.package_name == 'com.whatsapp' for app in APPS)


def test_build_pipeline_skips_apps_without_build(tmp_path, monkeypatch):
    fetched = []
    monkeypatch.setattr(crawler_module, 'APPS_PATH', tmp_path)
    monkeypatch.setattr(crawler_module, 'APPS', [BUILD_APP, ARTIFACTS_APP])
    monkeypatch.setattr(crawler_module, 'crawlers', [fake_crawler(fetched)])
    crawler_module.run_over_crawlers()
    assert fetched == ['com.example.build']
    assert apps_in('artifacts') == [ARTIFACTS_APP]


@pytest.mark.parametrize('value', ['build', 'artifacts', 'all'])
def test_pipeline_flag_parses(value):
    assert build_parser().parse_args(['--pipeline', value]).pipeline == value


def test_pipeline_flag_defaults_to_build():
    assert build_parser().parse_args([]).pipeline == 'build'


def test_pipeline_flag_rejects_anything_else():
    with pytest.raises(SystemExit):
        build_parser().parse_args(['--pipeline', 'nope'])


def test_whatsapp_config():
    [whatsapp] = [app for app in APPS if app.package_name == 'com.whatsapp']
    assert whatsapp.pipelines == frozenset({'build', 'artifacts'})
    assert whatsapp.direct_url == 'https://www.whatsapp.com/android/current/WhatsApp.apk'
    assert whatsapp.direct_source == 'whatsapp.com'


def test_paywall_only_required_for_build(tmp_path, monkeypatch):
    patchers_dir = tmp_path / 'patchers'
    (patchers_dir / 'WhatsAppPatcher').mkdir(parents=True)
    (patchers_dir / 'WhatsAppPatcher' / 'main.py').touch()
    monkeypatch.setenv('PATCHERS_DIR', str(patchers_dir))
    monkeypatch.delenv('PAYWALL_PATH', raising=False)
    check_patchers(apps_in('artifacts'), need_paywall=False)
    with pytest.raises(ValueError, match='PAYWALL_PATH is not set'):
        check_patchers(apps_in('artifacts'))


def test_patchers_still_required_without_paywall(tmp_path, monkeypatch):
    monkeypatch.setenv('PATCHERS_DIR', str(tmp_path))
    with pytest.raises(ValueError, match='WhatsAppPatcher'):
        check_patchers(apps_in('artifacts'), need_paywall=False)

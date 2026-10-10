import pytest

import crawler as crawler_module
from apps import AppConfig

MAKO = AppConfig(name='12+', package_name='com.keshet.mako.VOD')


@pytest.fixture
def apps_path(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler_module, 'APPS_PATH', tmp_path)
    return tmp_path


def add_local_versions(apps_path, *names):
    for name in names:
        (apps_path / MAKO.package_name / name).mkdir(parents=True)


def test_latest_local_version_compares_versions_not_text(apps_path):
    add_local_versions(apps_path, '43.0', '99.0', '100.0')
    assert crawler_module.get_latest_local_version(MAKO) == '100.0'


def test_names_that_are_not_versions_are_ignored(apps_path):
    add_local_versions(apps_path, '43.0', 'temp')
    assert crawler_module.get_latest_local_version(MAKO) == '43.0'


def test_no_local_versions_is_zero_and_creates_the_package_dir(apps_path):
    assert crawler_module.get_latest_local_version(MAKO) == '0.0.0'
    assert (apps_path / MAKO.package_name).is_dir()

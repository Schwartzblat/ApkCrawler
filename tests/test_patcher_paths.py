import pytest
from packaging.version import Version

import crawler as crawler_module
from apps import APPS, AppConfig
from crawler import check_patchers, patch_app

MAKO = AppConfig(name='12+', package_name='com.keshet.mako.VOD', patcher_name='MakoPatcher')


@pytest.fixture
def patcher_env(tmp_path, monkeypatch):
    """PATCHERS_DIR with a checkout of every patcher APPS names, and PAYWALL_PATH."""
    patchers_dir, paywall = tmp_path / 'patchers', tmp_path / 'paywall'
    for app in APPS:
        if app.patcher_name:
            (patchers_dir / app.patcher_name).mkdir(parents=True, exist_ok=True)
            (patchers_dir / app.patcher_name / 'main.py').touch()
    paywall.mkdir()
    monkeypatch.setenv('PATCHERS_DIR', str(patchers_dir))
    monkeypatch.setenv('PAYWALL_PATH', str(paywall))
    return patchers_dir, paywall


def test_patch_app_runs_the_patcher_in_patchers_dir_with_the_paywall(patcher_env, tmp_path, monkeypatch):
    patchers_dir, paywall = patcher_env
    calls = []

    class FakeProcess:
        def __init__(self, args, cwd):
            calls.append((args, cwd))

        @staticmethod
        def wait():
            return 0

    monkeypatch.setattr(crawler_module.subprocess, 'Popen', FakeProcess)
    apk_path = tmp_path / 'mako.apk'
    (tmp_path / 'patched_mako.apk').touch()
    assert patch_app(MAKO, Version('1.0'), apk_path) == tmp_path / 'patched_mako.apk'
    [(args, cwd)] = calls
    assert cwd == patchers_dir / 'MakoPatcher'
    assert args[args.index('--paywall') + 1] == str(paywall)


def test_relative_paths_are_resolved_against_the_working_directory(patcher_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('PAYWALL_PATH', 'paywall')
    assert crawler_module.env_path('PAYWALL_PATH') == tmp_path / 'paywall'


def test_check_passes_when_every_patcher_and_the_paywall_exist(patcher_env):
    check_patchers(APPS)


@pytest.mark.parametrize('variable', ['PATCHERS_DIR', 'PAYWALL_PATH'])
def test_check_fails_when_a_variable_is_unset(patcher_env, monkeypatch, variable):
    monkeypatch.delenv(variable)
    with pytest.raises(ValueError, match=f'{variable} is not set'):
        check_patchers(APPS)


def test_check_names_each_missing_patcher_and_the_paywall(patcher_env):
    patchers_dir, paywall = patcher_env
    (patchers_dir / 'MakoPatcher' / 'main.py').unlink()
    paywall.rmdir()
    with pytest.raises(ValueError) as error:
        check_patchers(APPS)
    assert str(patchers_dir / 'MakoPatcher' / 'main.py') in str(error.value)
    assert str(paywall) in str(error.value)
    assert 'WhatsAppPatcher' not in str(error.value)


def test_check_ignores_apps_without_a_patcher(patcher_env):
    check_patchers([AppConfig(name='OkCupid', package_name='com.okcupid.okcupid')])

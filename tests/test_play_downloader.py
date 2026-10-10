import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from packaging.version import Version

from apps import AppConfig
from crawlers import play_downloader
from crawlers.play_downloader import PlayCrawler
from utils import get_architectures

OKCUPID = AppConfig(name='OkCupid', package_name='com.okcupid.okcupid')

# Stands in for the aurora-dl CLI: same arguments, same stdout contract
# (info prints JSON; download prints the output directory last and writes manifest.json there).
FAKE_AURORA_DL = '''#!{python}
import io, json, sys, zipfile
from pathlib import Path

config = json.loads(Path({config!r}).read_text())
with open({calls!r}, "a") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\\n")
command, package = sys.argv[1], sys.argv[2]
if command == "versions":
    if config["versions_exit"]:
        sys.exit(config["versions_exit"])
    last = int(sys.argv[sys.argv.index("--last") + 1])
    print(json.dumps([{{"version_code": code, "version_name": name}} for code, name in config["releases"][:last]]))
    sys.exit(0)
if command == "info":
    if config["info_exit"]:
        print("error: not available", file=sys.stderr)
        sys.exit(config["info_exit"])
    print(json.dumps({{"package": package, "version_code": 6165, "version_name": config["version_name"]}}))
    sys.exit(0)
if config["download_exit"]:
    sys.exit(config["download_exit"])
version_code, version_name = 6165, config["version_name"]
if "--version-code" in sys.argv:
    version_code = int(sys.argv[sys.argv.index("--version-code") + 1])
    version_name = dict(config["releases"])[version_code]
out = Path(sys.argv[sys.argv.index("-o") + 1]) / package / str(version_code)
out.mkdir(parents=True)
files = []
for name, kind in config["files"]:
    if kind == "obb":
        content = b"OBB"
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as apk:
            apk.writestr("AndroidManifest.xml", name)
        content = buffer.getvalue()
    (out / name).write_bytes(content)
    files.append({{"name": name, "kind": kind, "size": len(content), "sha256": ""}})
manifest = {{"package": package, "version_code": version_code, "version_name": version_name, "files": files}}
(out / "manifest.json").write_text(json.dumps(manifest))
print("INFO: saved", file=sys.stderr)
print(out)
'''

RELEASES = [[6165, '116.0.0'], [6164, '115.1.0'], [6163, '115.0.0']]
SPLITS = [('base.apk', 'base'), ('split_config.arm64_v8a.apk', 'split'), ('split_config.xxhdpi.apk', 'split')]


@pytest.fixture(autouse=True)
def no_remembered_version_codes(monkeypatch):
    monkeypatch.setattr(play_downloader, '_version_codes', {})


@pytest.fixture
def fake_aurora_dl(tmp_path, monkeypatch):
    """Installs a fake aurora-dl via AURORA_DL; returns a function that reads the argument lists it was run with."""
    calls = tmp_path / 'calls.jsonl'

    def install(version_name='116.0.0', files=SPLITS, info_exit=0, download_exit=0, releases=RELEASES,
                versions_exit=0):
        config = tmp_path / 'fake_config.json'
        config.write_text(json.dumps({
            'version_name': version_name, 'files': files, 'info_exit': info_exit, 'download_exit': download_exit,
            'releases': releases, 'versions_exit': versions_exit,
        }))
        script = tmp_path / 'aurora-dl'
        script.write_text(FAKE_AURORA_DL.format(python=sys.executable, config=str(config), calls=str(calls)))
        script.chmod(0o755)
        monkeypatch.setenv('AURORA_DL', str(script))
        return lambda: [json.loads(line) for line in calls.read_text().splitlines()]

    return install


@pytest.fixture
def out_dir(tmp_path):
    path = tmp_path / 'out'
    path.mkdir()
    return path


def test_available_versions_is_plays_current_release(fake_aurora_dl):
    calls = fake_aurora_dl(version_name='116.0.0')
    assert PlayCrawler.get_available_versions(OKCUPID) == {'116.0.0': Version('116.0.0')}
    assert calls() == [['info', 'com.okcupid.okcupid']]


def test_app_play_cannot_deliver_yields_no_versions(fake_aurora_dl, capsys):
    fake_aurora_dl(info_exit=4)
    assert PlayCrawler.get_available_versions(OKCUPID) == {}
    assert 'OkCupid' in capsys.readouterr().out


def test_missing_aurora_dl_yields_no_versions(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('AURORA_DL', str(tmp_path / 'not-installed'))
    assert PlayCrawler.get_available_versions(OKCUPID) == {}
    assert 'not-installed' in capsys.readouterr().out


def test_unparseable_version_name_yields_no_versions(fake_aurora_dl):
    fake_aurora_dl(version_name='latest build')
    assert PlayCrawler.get_available_versions(OKCUPID) == {}


def test_splits_are_packed_as_an_xapk_with_apks_at_the_root(fake_aurora_dl, out_dir):
    fake_aurora_dl(files=SPLITS)
    path = PlayCrawler.download_specific_version(out_dir, OKCUPID, Version('116.0.0'))
    assert path == out_dir / 'com.okcupid.okcupid-116.0.0.xapk'
    with zipfile.ZipFile(path) as bundle:
        assert sorted(bundle.namelist()) == ['base.apk', 'split_config.arm64_v8a.apk', 'split_config.xxhdpi.apk']
        with zipfile.ZipFile(io.BytesIO(bundle.read('base.apk'))) as base:
            assert base.read('AndroidManifest.xml') == b'base.apk'
    assert get_architectures(path) == {'arm64-v8a'}  # crawler.py's arm64 gate reads the split name
    assert list(out_dir.iterdir()) == [path]


def test_single_apk_is_kept_as_an_apk(fake_aurora_dl, out_dir):
    fake_aurora_dl(files=[('base.apk', 'base')])
    path = PlayCrawler.download_specific_version(out_dir, OKCUPID, Version('116.0.0'))
    assert path == out_dir / 'com.okcupid.okcupid-116.0.0.apk'
    with zipfile.ZipFile(path) as apk:
        assert apk.read('AndroidManifest.xml') == b'base.apk'


def test_obb_files_are_left_out(fake_aurora_dl, out_dir):
    fake_aurora_dl(files=SPLITS + [('main.6165.com.okcupid.okcupid.obb', 'obb')])
    path = PlayCrawler.download_specific_version(out_dir, OKCUPID, Version('116.0.0'))
    with zipfile.ZipFile(path) as bundle:
        assert not [name for name in bundle.namelist() if name.endswith('.obb')]


def test_download_asks_for_the_package_into_a_temporary_root(fake_aurora_dl, out_dir):
    calls = fake_aurora_dl()
    PlayCrawler.download_specific_version(out_dir, OKCUPID, Version('116.0.0'))
    (command,) = calls()
    assert command[:2] == ['download', 'com.okcupid.okcupid']
    assert not Path(command[command.index('-o') + 1]).exists()  # temporary root is cleaned up


def test_play_moving_on_to_a_newer_version_is_refused(fake_aurora_dl, out_dir):
    fake_aurora_dl(version_name='117.0.0')
    with pytest.raises(ValueError, match='117.0.0'):
        PlayCrawler.download_specific_version(out_dir, OKCUPID, Version('116.0.0'))
    assert list(out_dir.iterdir()) == []


def test_failed_download_raises(fake_aurora_dl, out_dir):
    fake_aurora_dl(download_exit=6)
    with pytest.raises(RuntimeError, match='exit code 6'):
        PlayCrawler.download_specific_version(out_dir, OKCUPID, Version('116.0.0'))
    assert list(out_dir.iterdir()) == []


def test_backfill_lists_recent_releases_through_aurora_dl_versions(fake_aurora_dl):
    calls = fake_aurora_dl(releases=[[6165, '116.0.0'], [6164, '115.1.0'], [6163, None], [6162, 'build x']])
    assert PlayCrawler.get_available_versions(OKCUPID, 4) == {
        '116.0.0': Version('116.0.0'), '115.1.0': Version('115.1.0')}  # unnamed and unparseable ones are left out
    assert calls() == [['versions', 'com.okcupid.okcupid', '--last', '4']]


def test_a_count_of_one_asks_only_for_the_current_release(fake_aurora_dl):
    calls = fake_aurora_dl()
    assert PlayCrawler.get_available_versions(OKCUPID, 1) == {'116.0.0': Version('116.0.0')}
    assert calls() == [['info', 'com.okcupid.okcupid']]


def test_failed_versions_listing_yields_no_versions(fake_aurora_dl, capsys):
    fake_aurora_dl(versions_exit=5)
    assert PlayCrawler.get_available_versions(OKCUPID, 3) == {}
    assert 'OkCupid' in capsys.readouterr().out


def test_an_older_release_is_downloaded_by_its_version_code(fake_aurora_dl, out_dir):
    calls = fake_aurora_dl()
    PlayCrawler.get_available_versions(OKCUPID, 3)
    path = PlayCrawler.download_specific_version(out_dir, OKCUPID, Version('115.1.0'))
    assert path == out_dir / 'com.okcupid.okcupid-115.1.0.xapk'
    download = calls()[-1]
    assert download[download.index('--version-code') + 1] == '6164'

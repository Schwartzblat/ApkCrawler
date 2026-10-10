"""Google Play, through the aurora-dl CLI from the aurora_downloader project.

aurora-dl talks to Play the way Aurora Store does, with our own Google account, and checks
Play's hashes and signing certificate. Normally this source reports Play's current release;
asked for more (--backfill), it lists recent releases with `aurora-dl versions` and downloads
them by versionCode. Set AURORA_DL in .env if aurora-dl is not on PATH.
"""
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from packaging.version import InvalidVersion, Version

from apps import AppConfig
from crawlers.crawler import Crawler


# versionCodes of releases listed by `aurora-dl versions`, so their downloads ask for that exact build
_version_codes: Dict[Tuple[str, Version], int] = {}


def _aurora_dl() -> str:
    return os.environ.get('AURORA_DL', 'aurora-dl')


def _run(args: List[str]) -> subprocess.CompletedProcess:
    # aurora-dl logs to stderr, which goes straight to the console; stdout carries the result
    return subprocess.run([_aurora_dl(), *args], stdout=subprocess.PIPE, text=True)


def _query(app: AppConfig, args: List[str]) -> Optional[str]:
    """stdout of an aurora-dl listing command, or None (with a warning) when it cannot answer."""
    try:
        result = _run(args)
    except OSError as error:
        print(f'[-] Cannot run {_aurora_dl()}: {error}')
        return None
    if result.returncode != 0:
        print(f'[-] Google Play has nothing to download for {app.name} (aurora-dl exit code {result.returncode})')
        return None
    return result.stdout


def _versions(app: AppConfig, names: List[Tuple[Optional[str], Optional[int]]]) -> Dict[str, Version]:
    versions = {}
    for name, version_code in names:
        try:
            version = Version(name)
        except (InvalidVersion, TypeError):
            print(f'[-] Cannot compare Google Play version {name!r} of {app.name}')
            continue
        versions[name] = version
        if version_code:
            _version_codes[(app.package_name, version)] = version_code
    return versions


def _pack(apks: List[Path], output_path: Path, name: str) -> Path:
    """Keeps a lone APK as is; puts splits into an .xapk with every APK at the zip root, the layout Stitch reads as a bundle."""
    if len(apks) == 1:
        target = output_path / f'{name}.apk'
        shutil.copyfile(apks[0], target)
        return target
    target = output_path / f'{name}.xapk'
    with zipfile.ZipFile(target, 'w') as bundle:
        for apk in apks:
            bundle.write(apk, apk.name)
    return target


class PlayCrawler(Crawler):
    name = "Google Play"

    @staticmethod
    def get_available_versions(app: AppConfig, count: Optional[int] = None) -> Dict[str, Version]:
        if count and count > 1:
            output = _query(app, ['versions', app.package_name, '--last', str(count)])
            releases = json.loads(output) if output is not None else []
            return _versions(app, [(release['version_name'], release['version_code']) for release in releases])
        output = _query(app, ['info', app.package_name])
        return _versions(app, [(json.loads(output)['version_name'], None)]) if output is not None else {}

    @staticmethod
    def download_specific_version(output_path: Path, app: AppConfig, version: Version) -> Path:
        with tempfile.TemporaryDirectory() as temp_root:
            args = ['download', app.package_name, '-o', temp_root]
            version_code = _version_codes.get((app.package_name, version))
            if version_code:
                args += ['--version-code', str(version_code)]
            result = _run(args)
            if result.returncode != 0:
                raise RuntimeError(f'aurora-dl download of {app.package_name} failed with exit code {result.returncode}')
            download_dir = Path(result.stdout.strip().splitlines()[-1])
            manifest = json.loads((download_dir / 'manifest.json').read_text())
            if Version(manifest['version_name']) != version:
                raise ValueError(f'Google Play now serves {app.name} {manifest["version_name"]}, not {version}')
            apks = [download_dir / file['name'] for file in manifest['files'] if file['kind'] != 'obb']
            return _pack(apks, output_path, f'{app.package_name}-{version}')

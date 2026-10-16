import argparse
import os
import shlex
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Set
from packaging.version import InvalidVersion, Version
import subprocess

import artifacts.pipeline as artifacts_pipeline
from apps import APPS, AppConfig
from crawlers.crawler import Crawler
from crawlers.apkmirror_downloader import APKMirrorCrawler
from crawlers.apkpure_downloader import APKPureCrawler
from crawlers.play_downloader import PlayCrawler
from utils import get_architectures

crawlers = [
    PlayCrawler,
    APKPureCrawler,
    APKMirrorCrawler,
]

APPS_PATH = Path('/opt/patched')
# Environment variables, set in .env, locating the checkouts patch_app runs: the directory holding
# a <patcher_name>/main.py per app, and the PatchPaywall passed to every patcher
PATCHERS_DIR = 'PATCHERS_DIR'
PAYWALL_PATH = 'PAYWALL_PATH'
PIPELINES = ('build', 'artifacts', 'all')
# Environment variables of the artifacts pipeline (ARTIFACTS_DIR is also read by artifacts.alerts)
PATCH_SERVER_URL = 'PATCH_SERVER_URL'
CRAWLER_SECRET = 'CRAWLER_SECRET'
ARTIFACTS_DIR = 'ARTIFACTS_DIR'
DEFAULT_ARTIFACTS_DIR = '~/.local/share/androidmod-crawler'


def env_path(variable: str) -> Path:
    value = os.environ.get(variable)
    if not value:
        raise ValueError(f'{variable} is not set')
    return Path(value).expanduser().absolute()


def check_patchers(apps: Iterable[AppConfig], need_paywall: bool = True) -> None:
    """Fails before anything is downloaded when a patcher an app names is missing, or the paywall
    when need_paywall (only the build pipeline passes it to the patchers)."""
    patchers_dir = env_path(PATCHERS_DIR)
    paywall = env_path(PAYWALL_PATH) if need_paywall else None
    missing = [patchers_dir / app.patcher_name / 'main.py' for app in apps
               if app.patcher_name and not (patchers_dir / app.patcher_name / 'main.py').is_file()]
    if paywall and not paywall.exists():
        missing.append(paywall)
    if missing:
        raise ValueError(f'missing {", ".join(map(str, missing))}')


def get_local_versions(app: AppConfig) -> Set[Version]:
    package_path = APPS_PATH / app.package_name
    os.makedirs(package_path, exist_ok=True)
    versions = set()
    for name in os.listdir(package_path):
        try:
            versions.add(Version(name))
        except InvalidVersion:
            continue
    return versions


def get_latest_local_version(app: AppConfig) -> str:
    return str(max(get_local_versions(app), default=Version('0.0.0')))


def versions_to_fetch(local: Set[Version], available: Iterable[Version], backfill: int = 0) -> List[Version]:
    """Releases newer than the newest local one; with backfill, also those missing among the newest
    `backfill` releases known to any source or kept locally. Oldest first."""
    available = set(available)
    latest = max(local, default=Version('0.0.0'))
    wanted = {version for version in available if version > latest}
    if backfill:
        wanted |= set(sorted(available | local, reverse=True)[:backfill]) - local
    return sorted(wanted)


def patch_app(app: AppConfig, version: Version, apk_path: Path) -> Optional[Path]:
    output_path = apk_path.parent / ('patched_' + apk_path.name)
    args = [
        'python3',
        f'main.py',
        '-p', str(apk_path),
        '-o', str(output_path),
        '--no-sign',
        '--paywall', str(env_path(PAYWALL_PATH))
    ]
    if os.environ.get('GOOGLE_API_KEY'):
        args += ['-g', os.environ.get('GOOGLE_API_KEY')]
    process = subprocess.Popen(args, cwd=env_path(PATCHERS_DIR) / app.patcher_name)
    if process.wait() != 0 or not output_path.exists():
        print(f'[-] Failed to patch {app.name} version {version}')
        return None
    return output_path


def upload(patched_path: Path, remote: str) -> None:
    """Copies a patched APK over SSH to the same package/version folder under the remote root."""
    host, _, remote_root = remote.partition(':')
    remote_dir = PurePosixPath(remote_root or APPS_PATH) / patched_path.parent.relative_to(APPS_PATH).as_posix()
    print(f'Uploading {patched_path.name} to {host}:{remote_dir} ...')
    subprocess.run(['ssh', host, 'mkdir', '-p', shlex.quote(str(remote_dir))], check=True)
    subprocess.run(['scp', str(patched_path), f'{host}:{remote_dir}/'], check=True)


def fetch(app: AppConfig, version: Version, sources: List[Crawler]) -> Optional[Path]:
    """Downloads an arm64 build of a version from the first source that can deliver one."""
    version_path = APPS_PATH / app.package_name / str(version)
    for crawler in sources:
        os.makedirs(version_path, exist_ok=True)
        try:
            apk_path = crawler.download_specific_version(version_path, app, version)
        except Exception as error:
            print(f'[-] {crawler.name} failed to download {app.name} {version}: {error}')
            continue
        architectures = get_architectures(apk_path)
        if architectures and 'arm64-v8a' not in architectures:
            print(f'[-] {crawler.name} only has {", ".join(sorted(architectures))} for {app.name} {version}, skipping')
            os.remove(apk_path)
            continue
        return apk_path
    if version_path.exists() and not os.listdir(version_path):
        os.rmdir(version_path)
    return None


def apps_in(pipeline: str) -> List[AppConfig]:
    return [app for app in APPS if pipeline in app.pipelines]


def run_over_crawlers(remote: Optional[str] = None, backfill: int = 0):
    for app in apps_in('build'):
        local_versions = get_local_versions(app)
        print(f'Latest version for {app.name}: {max(local_versions, default=Version("0.0.0"))}')
        sources: Dict[Version, List[Crawler]] = {}
        for crawler in crawlers:
            available_versions = crawler.get_available_versions(app, backfill) if backfill \
                else crawler.get_available_versions(app)
            print(f'Available versions on {crawler.name} for {app.name}: {sorted(available_versions.values())}')
            for version in available_versions.values():
                sources.setdefault(version, []).append(crawler)
        for version in versions_to_fetch(local_versions, sources, backfill):
            print(f'Version {version} of {app.name} is missing, fetching it')
            apk_path = fetch(app, version, sources[version])
            if apk_path is None:
                print(f'[-] No source could deliver {app.name} {version}')
                continue
            if not app.patcher_name:
                print(f'{app.name} has no patcher, keeping the unpatched {apk_path.name}')
                continue
            print(f'Patching {app.name} version {version} at {apk_path} ...')
            patched_path = patch_app(app, version, apk_path)
            if patched_path and remote:
                upload(patched_path, remote)


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f'expected 1 or more, got {number}')
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Downloads new versions of the apps and patches them',
                                     epilog=f'Patching needs {PATCHERS_DIR}, the directory holding the patchers,'
                                            f' and {PAYWALL_PATH}, the PatchPaywall checkout')
    parser.add_argument('-r', '--remote', help=f'Upload the patched APKs over SSH to user@server[:path],'
                                               f' path defaults to {APPS_PATH}')
    parser.add_argument('-b', '--backfill', type=positive, metavar='N', default=0,
                        help='Also download the missing ones among each app\'s newest N releases')
    parser.add_argument('--pipeline', choices=PIPELINES, default='build',
                        help='build: download and patch new releases (default); artifacts: record'
                             ' signature-finder results; all: both')
    parser.add_argument('--retry-failed', action='store_true',
                        help='artifacts pipeline: retry APKs parked by a patcher crash or a rejected record')
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    runs_build = args.pipeline in ('build', 'all')
    runs_artifacts = args.pipeline in ('artifacts', 'all')
    if args.retry_failed and not runs_artifacts:
        parser.error('--retry-failed needs --pipeline artifacts or all')
    if runs_artifacts:
        for variable in (PATCH_SERVER_URL, CRAWLER_SECRET):
            if not os.environ.get(variable):
                parser.error(f'{variable} is not set')
        if not os.environ[PATCH_SERVER_URL].lower().startswith(('http://', 'https://')):
            parser.error(f'{PATCH_SERVER_URL} must start with http:// or https://')
    apps =(apps_in('build') if runs_build else []) + (apps_in('artifacts') if runs_artifacts else [])
    apps = list({app.package_name: app for app in apps}.values())
    try:
        check_patchers(apps, need_paywall=runs_build)
    except ValueError as error:
        parser.error(str(error))
    if runs_build:
        run_over_crawlers(remote=args.remote, backfill=args.backfill)
    if runs_artifacts:
        artifacts_dir = Path(os.environ.get(ARTIFACTS_DIR) or DEFAULT_ARTIFACTS_DIR).expanduser().absolute()
        artifacts_pipeline.run(apps_in('artifacts'), env_path(PATCHERS_DIR), artifacts_dir,
                               os.environ[PATCH_SERVER_URL], os.environ[CRAWLER_SECRET],
                               retry_failed=args.retry_failed)


if __name__ == '__main__':
    main()

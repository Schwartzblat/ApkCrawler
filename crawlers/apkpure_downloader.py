import shutil
from time import sleep

from packaging.version import Version

from apps import AppConfig
from crawlers.crawler import Crawler
from utils import get_extension, download_apk_from_url
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import parse_qs, urlparse
import requests
import re

APPLICATION_VERSION_RE = re.compile(
    '<a class="downloadLink" href=".*?((?:[0-9]+-?)+)-.*?">'
)
download_link_re = re.compile('href=\"([^"]*download/download/[^"]*?)"')
click_here_re = re.compile('href="(.*APKMirror/download.php.id=.*?)"')

headers = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 ("
                  "KHTML, like Gecko) Chrome/136.0.7103.126 Mobile Safari/537.36"
}

VERSIONS_RE = re.compile(r'\"(?P<version_name>[^"]+)\"\n *data-dt-versioncode="(?P<version_code>\d*)')
DOWNLOAD_LINK_RE = re.compile(r'\"(https://d.apkpure.com/b/[^\"]*)\"')


class APKPureCrawler(Crawler):
    name = "APKPure"

    @staticmethod
    def get_latest_version_download_link(package_name: str) -> Optional[str]:
        return f'https://d.apkpure.com/b/XAPK/{package_name}?version=latest'

    @staticmethod
    def get_available_versions(app: AppConfig, count: Optional[int] = None) -> Dict[str, Version]:
        if not app.apkpure_app_path:
            return {}
        versions_html = requests.get(
            f"https://www.apkpure.com/{app.apkpure_app_path}/versions", headers=headers
        ).text
        versions = VERSIONS_RE.findall(versions_html)[:count or 5][::-1]
        return {v[0]: Version(v[0]) for v in versions}

    @staticmethod
    def download_latest(package_name: str, out_name: str):
        download_link = APKPureCrawler.get_latest_version_download_link(package_name).replace("&amp;", "&")
        if not download_link:
            print("[-] Failed to get a valid download link")
            return None
        res = requests.get(download_link, headers=headers)
        with open(out_name, "wb") as f:
            f.write(res.content)
        new_name = f"{out_name}.{get_extension(Path(out_name))}"
        shutil.move(out_name, new_name)
        return new_name

    @staticmethod
    def pick_supported_link(links: List[str]) -> str:
        """APKPure has a link per architecture (nc=...), links without one leave the choice to APKPure."""
        architectures = {link: parse_qs(urlparse(link).query).get('nc', [''])[0] for link in links}
        arm64_links = [link for link, arch in architectures.items() if 'arm64-v8a' in arch]
        untagged_links = [link for link, arch in architectures.items() if not arch]
        if not arm64_links + untagged_links:
            raise ValueError(f"No arm64 download found on APKPure, only: {set(architectures.values())}")
        return (arm64_links + untagged_links)[0]

    @staticmethod
    def download_specific_version(output_path: Path, app: AppConfig, version: Version) -> Path:
        session = requests.Session()
        session.headers = headers
        download_page = session.get(f'https://apkpure.com/{app.apkpure_app_path}/download/{str(version)}').text
        links = [link.replace("&amp;", "&") for link in DOWNLOAD_LINK_RE.findall(download_page)]
        download_link = APKPureCrawler.pick_supported_link(links)

        sleep(1)
        return download_apk_from_url(session, download_link, output_path, app.package_name, str(version))

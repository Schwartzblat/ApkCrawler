import re
from pathlib import Path
from time import sleep
from typing import Dict, Optional

from packaging.version import Version

from apps import AppConfig
from crawlers.cloudflare import CloudflareSession
from crawlers.crawler import Crawler
from utils import download_apk_from_url

download_link_re = re.compile('href=\"([^"]*download/download/[^"]*?)"')
click_here_re = re.compile('href="(.*APKMirror/download.php.id=.*?)"')
VARIANT_ROW_SEPARATOR = '<div class="table-row headerFont">'
variant_link_re = re.compile('href="([^"]+)"')
variant_bundle_re = re.compile(r'class="apkm-badge[^"]*"[^>]*>\s*BUNDLE\s*<')
table_cell_text_re = re.compile(r'<div class="table-cell[^"]*">\s*([^<]*?)\s*</div>')
SUPPORTED_ARCHITECTURES = ("arm64-v8a", "universal", "noarch")
pre_release_re = re.compile(r"\b(alpha|beta)\b", re.IGNORECASE)

apk_mirror_url = "https://www.apkmirror.com"


class APKMirrorCrawler(Crawler):
    name = "APKMirror"

    @staticmethod
    def get_available_versions(app: AppConfig, count: Optional[int] = None) -> Dict[str, Version]:
        if not app.apkmirror_url_template:
            return {}
        versions_html = CloudflareSession().get(
            f"{apk_mirror_url}/uploads/?appcategory={app.apkmirror_app_id}"
        ).text
        # Each release is linked with its title, which is the only place that marks it as a beta
        release_re = re.compile(
            'href="' + re.escape(app.apkmirror_url_template).replace(r"\{\}", "([0-9-]+)") + '">([^<]*)</a>'
        )
        stable_versions = [v for v, title in release_re.findall(versions_html) if not pre_release_re.search(title)]
        versions = list(dict.fromkeys(stable_versions))[:count or 5][::-1]
        return {v: Version(v.replace("-", ".")) for v in versions}

    @staticmethod
    def find_supported_variant(release_page: str) -> str:
        """Returns the download page of an arm64 or universal variant, preferring APKs over bundles."""
        variants = []
        for row in release_page.split(VARIANT_ROW_SEPARATOR)[1:]:
            link = variant_link_re.search(row)
            cells = table_cell_text_re.findall(row)
            if not link or not cells:
                continue
            architecture = cells[0]
            if any(arch in architecture for arch in SUPPORTED_ARCHITECTURES):
                variants.append((bool(variant_bundle_re.search(row)), architecture, link.group(1)))
        if not variants:
            raise ValueError("No arm64 or universal variant found on APKMirror")
        is_bundle, architecture, link = min(variants, key=lambda v: v[0])
        print(f"Selected {architecture} {'bundle' if is_bundle else 'APK'} variant: {link}")
        return link

    @staticmethod
    def download_specific_version(output_path: Path, app: AppConfig, version: Version) -> Path:
        session = CloudflareSession()
        release_page = session.get(apk_mirror_url + app.apkmirror_url_template.format(version)).text
        sleep(1)
        download_page = session.get(apk_mirror_url + APKMirrorCrawler.find_supported_variant(release_page)).text
        download_link = download_link_re.findall(download_page)[0]
        sleep(1)
        click_here_page = session.get(f"{apk_mirror_url}{download_link}").text
        click_here_url = click_here_re.findall(click_here_page)[0].replace("&amp;", "&")
        sleep(1)
        return download_apk_from_url(session, f"{apk_mirror_url}{click_here_url}", output_path, app.package_name, str(version))

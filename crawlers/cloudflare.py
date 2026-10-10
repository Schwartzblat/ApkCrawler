import asyncio
import json
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

import requests
import zendriver

CLEARANCE_DIR = Path(__file__).parent.parent / '.cloudflare'
CLEARANCE_PATH = CLEARANCE_DIR / 'clearance.json'
BROWSER_PROFILE_PATH = CLEARANCE_DIR / 'chrome-profile'
CHALLENGE_TIMEOUT_SECONDS = 10 * 60
DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" \
                     " (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"


def is_challenge(response: requests.Response) -> bool:
    return response.headers.get('cf-mitigated') == 'challenge'


def passes_with(url: str, user_agent: str, cookies: List[Dict[str, str]]) -> bool:
    jar = {cookie['name']: cookie['value'] for cookie in cookies}
    with requests.get(url, headers={'User-Agent': user_agent}, cookies=jar, stream=True) as response:
        return not is_challenge(response)


async def get_clearance(url: str) -> dict:
    """
    Opens Chrome on the challenged page and waits until its Cloudflare cookies also work outside the browser.
    Cloudflare either lets the window through on its own, or asks you to tick "Verify you are human".
    """
    host = urlparse(url).hostname
    browser = await zendriver.start(headless=False, user_data_dir=str(BROWSER_PROFILE_PATH))
    try:
        page = await browser.get(url)
        print(f'[!] Cloudflare is checking {host} - if it asks, tick "Verify you are human" in the Chrome window')
        user_agent = await page.evaluate('navigator.userAgent')
        checked_clearance = None
        for _ in range(CHALLENGE_TIMEOUT_SECONDS // 2):
            await asyncio.sleep(2)
            cookies = [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path}
                       for c in await browser.cookies.get_all() if host.endswith(c.domain.lstrip('.'))]
            clearance = next((c['value'] for c in cookies if c['name'] == 'cf_clearance'), None)
            if clearance and clearance != checked_clearance:
                checked_clearance = clearance
                if passes_with(url, user_agent, cookies):
                    return {'user_agent': user_agent, 'cookies': cookies}
        raise TimeoutError(f'Cloudflare check on {host} was not completed within {CHALLENGE_TIMEOUT_SECONDS}s')
    finally:
        await browser.stop()


class CloudflareSession(requests.Session):
    """A session that reuses a saved Cloudflare clearance, and renews it in a Chrome window when challenged."""

    def __init__(self):
        super().__init__()
        self.headers['User-Agent'] = DEFAULT_USER_AGENT
        if CLEARANCE_PATH.exists():
            self._apply_clearance(json.loads(CLEARANCE_PATH.read_text()))

    def request(self, method, url, *args, **kwargs):
        response = super().request(method, url, *args, **kwargs)
        if not is_challenge(response):
            return response
        response.close()
        clearance = asyncio.run(get_clearance(url))
        CLEARANCE_DIR.mkdir(exist_ok=True)
        CLEARANCE_PATH.write_text(json.dumps(clearance))
        self._apply_clearance(clearance)
        return super().request(method, url, *args, **kwargs)

    def _apply_clearance(self, clearance: dict) -> None:
        # Cloudflare ties the clearance to the browser's user agent
        self.headers['User-Agent'] = clearance['user_agent']
        for cookie in clearance['cookies']:
            self.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie['path'])

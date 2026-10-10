import re
import shutil
from pathlib import Path
import zipfile
from time import sleep
from typing import IO, Set, Union

import requests
from tqdm import tqdm

# Split APKs holding the native code for one ABI, e.g. config.arm64_v8a.apk (XAPK) or split_config.arm64_v8a.apk (APKM)
ABI_SPLIT_RE = re.compile(r'(?:split_)?config\.(arm64_v8a|armeabi_v7a|armeabi|x86_64|x86|mips64|mips)\.apk')


def is_bundle(filepath: Path) -> bool:
    with zipfile.ZipFile(filepath, 'r') as zip_file:
        for file in zip_file.namelist():
            if file.endswith('.apk'):
                return True
    return False


def get_architectures(apk: Union[Path, IO[bytes]]) -> Set[str]:
    """Native ABIs of an APK or bundle, empty when it has no native code."""
    architectures = set()
    with zipfile.ZipFile(apk, 'r') as zip_file:
        for file in zip_file.namelist():
            split = ABI_SPLIT_RE.fullmatch(file)
            if split:
                architectures.add(split.group(1).replace('_', '-'))
            elif file.startswith('lib/') and file.count('/') >= 2:
                architectures.add(file.split('/')[1])
            elif file.endswith('.apk'):
                with zip_file.open(file) as inner_apk:
                    architectures |= get_architectures(inner_apk)
    return architectures


def get_extension(filepath: Path) -> str:
    if is_bundle(filepath):
        return 'xapk'
    return 'apk'


def download_apk_from_url(session: requests.Session, download_link: str, output_path: Path, app_name: str,
                          version: str) -> Path:
    block_size = 1024
    temp_path = output_path / 'out'
    for _ in range(5):
        try:
            res = session.get(download_link, stream=True, timeout=300)
            total_size = int(res.headers.get('content-length', 0))
            with tqdm(total=total_size, unit='B', unit_scale=True, colour='white') as bar:
                with open(temp_path, "wb") as f:
                    for data in res.iter_content(block_size):
                        f.write(data)
                        bar.update(len(data))
            break
        except Exception:
            print("[-] Failed to download version, retrying...")
            sleep(1)
            if _ == 4:
                raise Exception("[-] Failed to download version after multiple attempts")
    final_path = output_path / f'{app_name}-{version}.{get_extension(Path(temp_path))}'
    shutil.move(temp_path, final_path)
    return final_path

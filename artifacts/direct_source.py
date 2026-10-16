"""Probe and download an app's direct APK URL."""
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import requests

from artifacts.state import AppState


@dataclass
class Probe:
    etag: Optional[str]
    last_modified: Optional[str]
    length: Optional[int]


def _probe_from(response) -> Probe:
    length = response.headers.get('Content-Length')
    return Probe(
        etag=response.headers.get('ETag'),
        last_modified=response.headers.get('Last-Modified'),
        length=int(length) if length is not None and length.isdigit() else None,
    )


def probe(url: str, timeout=30) -> Probe:
    response = requests.head(url, allow_redirects=True, timeout=timeout)
    response.raise_for_status()
    return _probe_from(response)


def unchanged(probe: Probe, state: AppState) -> bool:
    if probe.etag is not None:
        return probe.etag == state.etag
    if probe.last_modified is None or probe.length is None:
        return False
    return probe.last_modified == state.last_modified and probe.length == state.length


def download(url: str, dest_dir: Path, timeout=600) -> Tuple[Path, str, Probe]:
    """Stream url into dest_dir/<sha256>.apk. The Probe describes this GET's own headers."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix='.download-', suffix='.part', dir=dest_dir)
    try:
        sha = hashlib.sha256()
        written = 0
        with os.fdopen(fd, 'wb') as f, \
                requests.get(url, stream=True, allow_redirects=True, timeout=timeout) as response:
            response.raise_for_status()
            got = _probe_from(response)
            for chunk in response.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                sha.update(chunk)
                written += len(chunk)
        if got.length is not None and written != got.length:
            raise requests.exceptions.ChunkedEncodingError(
                'incomplete download: %d of %d bytes' % (written, got.length))
        digest = sha.hexdigest()
        final = dest_dir / (digest + '.apk')
        os.replace(tmp_name, final)
        return final, digest, got
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

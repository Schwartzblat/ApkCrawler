"""Per-app pipeline state: ARTIFACTS_DIR/<package>/state.json (APKs in apks/<sha256>.apk)."""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Kept:
    apk_sha256: str
    path: str
    version_code: int  # 0 until a record has been read
    downloaded_at: str
    processed_with: Optional[str]
    posted: bool
    last_error: Optional[str]


@dataclass
class AppState:
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    length: Optional[int] = None
    kept: List[Kept] = field(default_factory=list)
    alerted: Dict[str, str] = field(default_factory=dict)


def _state_path(artifacts_dir: Path, package: str) -> Path:
    return Path(artifacts_dir) / package / 'state.json'


def load(artifacts_dir: Path, package: str) -> AppState:
    path = _state_path(artifacts_dir, package)
    if not path.exists():
        return AppState()
    data = json.loads(path.read_text())
    return AppState(
        etag=data.get('etag'),
        last_modified=data.get('last_modified'),
        length=data.get('length'),
        kept=[Kept(**k) for k in data.get('kept', [])],
        alerted=dict(data.get('alerted', {})),
    )


def save(artifacts_dir: Path, package: str, state: AppState) -> None:
    path = _state_path(artifacts_dir, package)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w') as f:
        json.dump(asdict(state), f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

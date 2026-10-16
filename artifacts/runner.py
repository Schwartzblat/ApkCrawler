"""Run a patcher's signature finders (main.py --artifactory-only) and read the version record."""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from apps import AppConfig

_TAIL_LINES = 40
_VERSION_RE = re.compile(r'^PATCHER_VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
# The patcher processes downloaded third-party APKs and needs none of these
_SECRET_VARIABLES = frozenset({'CRAWLER_SECRET', 'BUNDLE_UPLOAD_SECRET', 'SMTP_PASSWORD', 'KEYSTORE_PASSWORD',
                               'KEY_PASSWORD'})


class RunnerError(Exception):
    pass


def patcher_version(patchers_dir: Path, patcher_name: str) -> str:
    path = Path(patchers_dir) / patcher_name / 'constants.py'
    try:
        text = path.read_text()
    except OSError as e:
        raise RunnerError(f'cannot read {path}: {e}')
    match = _VERSION_RE.search(text)
    if not match:
        raise RunnerError(f'no PATCHER_VERSION in {path}')
    return match.group(1)


def _tail(output: str) -> str:
    return '\n'.join(output.splitlines()[-_TAIL_LINES:])


def run_artifactory_only(patchers_dir: Path, app: AppConfig, apk: Path, timeout: int = 600,
                         work_root: Optional[Path] = None) -> Tuple[dict, bool]:
    """Returns (record, supported): exit 0 is supported, 3 unsupported; anything else raises RunnerError.
    The work dir is created under work_root (default: the system temp dir) and removed afterwards."""
    patcher_dir = Path(patchers_dir) / app.patcher_name
    if work_root is not None:
        Path(work_root).mkdir(parents=True, exist_ok=True)
    parent = tempfile.mkdtemp(dir=work_root)
    env = {name: value for name, value in os.environ.items() if name not in _SECRET_VARIABLES}
    try:
        out = os.path.join(parent, 'record.json')
        temp = os.path.join(parent, 'work')  # not created: Stitch refuses an existing temp dir
        proc = subprocess.Popen(
            [sys.executable, 'main.py', '--artifactory-only', out, '-p', str(apk), '-t', temp],
            cwd=patcher_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors='replace', start_new_session=True)
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            output, _ = proc.communicate()
            raise RunnerError(f'{app.patcher_name} timed out after {timeout}s\n{_tail(output or "")}')
        if proc.returncode not in (0, 3):
            raise RunnerError(f'{app.patcher_name} exited {proc.returncode}\n{_tail(output)}')
        try:
            with open(out) as f:
                record = json.load(f)
        except (OSError, ValueError) as e:
            raise RunnerError(f'{app.patcher_name} wrote no valid record ({e})\n{_tail(output)}')
        return record, proc.returncode == 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)

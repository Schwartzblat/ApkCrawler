"""Fake patcher directory: <patchers_dir>/<name>/main.py + constants.py.

The fake main.py reads behavior.json next to it on every run, so a test can change
behaviour between runs with set_behavior(); each call is appended to calls.jsonl.
"""
import json
from pathlib import Path
from typing import List, Optional

_MAIN = '''\
import argparse, json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--artifactory-only", dest="out", required=True)
ap.add_argument("-p", dest="apk", required=True)
ap.add_argument("-t", dest="temp", required=True)
args = ap.parse_args()
with open(os.path.join(here, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "temp_existed": os.path.exists(args.temp),
                        "out": args.out, "temp": args.temp, "env_names": sorted(os.environ)}) + "\\n")
with open(os.path.join(here, "behavior.json")) as f:
    b = json.load(f)
for line in b.get("print_lines", []):
    print(line)
    sys.stdout.flush()
if b.get("stderr_line"):
    print(b["stderr_line"], file=sys.stderr)
    sys.stderr.flush()
if b.get("sleep"):
    time.sleep(b["sleep"])
if b.get("raw_out") is not None:
    with open(args.out, "w") as f:
        f.write(b["raw_out"])
elif b.get("record") is not None:
    with open(args.out, "w") as f:
        json.dump(b["record"], f)
sys.exit(b.get("exit", 0))
'''

# Shaped like WhatsAppPatcher's record: exactly these 10 fields, with these types
SAMPLE_RECORD = {
    "package": "com.whatsapp", "version_code": 252010001, "version_name": "2.25.1.1",
    "apk_sha256": "ab" * 32, "dex_sha256": "cd" * 32, "patcher_version": "3.0.0",
    "artifacts": {"CONTACT_JID_CLASS_NAME": "X.AbC", "CONTACT_JID_METHOD_NAME": "A01"},
    "missing_keys": [], "features_off": [], "supported": True,
}


def set_behavior(patcher_dir: Path, *, exit: int = 0, record: Optional[dict] = None, raw_out: Optional[str] = None,
                 print_lines: Optional[List[str]] = None, stderr_line: Optional[str] = None,
                 sleep: float = 0) -> None:
    (Path(patcher_dir) / 'behavior.json').write_text(json.dumps({
        'exit': exit, 'record': record, 'raw_out': raw_out,
        'print_lines': print_lines or [], 'stderr_line': stderr_line, 'sleep': sleep}))


def set_version(patcher_dir: Path, version: str) -> None:
    (Path(patcher_dir) / 'constants.py').write_text(f'PATCHER_VERSION = "{version}"\n')


def make_fake_patcher(patchers_dir: Path, patcher_name: str, version: str = '3.0.0', **behavior) -> Path:
    """Create the fake patcher and return its directory. Default behaviour: write SAMPLE_RECORD, exit 0."""
    d = Path(patchers_dir) / patcher_name
    d.mkdir(parents=True, exist_ok=True)
    (d / 'main.py').write_text(_MAIN)
    set_version(d, version)
    behavior.setdefault('record', SAMPLE_RECORD)
    set_behavior(d, **behavior)
    return d


def calls(patcher_dir: Path) -> List[dict]:
    p = Path(patcher_dir) / 'calls.jsonl'
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

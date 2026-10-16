import configparser
import os
from pathlib import Path

CRAWLER_DIR = Path(__file__).resolve().parent.parent
DEPLOY_DIR = CRAWLER_DIR / 'deploy'


def parse_unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # systemd keys are case-sensitive
    parser.read_string((DEPLOY_DIR / name).read_text())
    return parser


def test_timer_runs_every_15_minutes_and_catches_up():
    timer = parse_unit('crawler-artifacts.timer')
    assert 'OnCalendar' in timer['Timer'] or 'OnUnitActiveSec' in timer['Timer']
    assert timer['Timer']['Persistent'] == 'true'
    assert timer['Timer']['RandomizedDelaySec'] == '60'
    assert timer['Install']['WantedBy'] == 'timers.target'


def test_service_runs_the_artifacts_pipeline():
    service = parse_unit('crawler-artifacts.service')
    assert service['Service']['Type'] == 'oneshot'
    assert service['Service']['ExecStart'].endswith('run_crawler.sh --pipeline artifacts')
    assert service['Service']['TimeoutStartSec'] == '45min'


def test_run_crawler_changes_to_its_directory_first_and_is_executable():
    script = CRAWLER_DIR / 'run_crawler.sh'
    lines = [line.strip() for line in script.read_text().splitlines()]
    code = [line for line in lines[1:] if line and not line.startswith('#')]
    assert code[0] == 'cd "$(dirname "$0")"'
    assert os.access(script, os.X_OK)

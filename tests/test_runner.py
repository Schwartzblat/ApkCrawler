import os
import tempfile

import pytest

from apps import AppConfig
from artifacts.runner import RunnerError, patcher_version, run_artifactory_only
from fakepatcher import SAMPLE_RECORD, calls, make_fake_patcher, set_behavior, set_version

APP = AppConfig(name='Fake', package_name='com.fake', patcher_name='FakePatcher')


@pytest.fixture
def tmproot(tmp_path, monkeypatch):
    """Point tempfile at a private dir so leaks are detectable."""
    root = tmp_path / 'tmp'
    root.mkdir()
    monkeypatch.setattr(tempfile, 'tempdir', str(root))
    return root


@pytest.fixture
def apk(tmp_path):
    p = tmp_path / 'a.apk'
    p.write_bytes(b'x')
    return p


def test_patcher_version_reads_constant(tmp_path):
    make_fake_patcher(tmp_path, 'FakePatcher', version='3.0.0')
    assert patcher_version(tmp_path, 'FakePatcher') == '3.0.0'
    set_version(tmp_path / 'FakePatcher', '3.1.4')
    assert patcher_version(tmp_path, 'FakePatcher') == '3.1.4'


def test_patcher_version_missing_raises(tmp_path):
    d = make_fake_patcher(tmp_path, 'FakePatcher')
    (d / 'constants.py').write_text('OTHER = "1"\n')
    with pytest.raises(RunnerError):
        patcher_version(tmp_path, 'FakePatcher')
    (d / 'constants.py').unlink()
    with pytest.raises(RunnerError):
        patcher_version(tmp_path, 'FakePatcher')


def test_exit_0_returns_record_supported(tmp_path, tmproot, apk):
    d = make_fake_patcher(tmp_path, 'FakePatcher')
    record, supported = run_artifactory_only(tmp_path, APP, apk)
    assert record == SAMPLE_RECORD and supported is True
    (call,) = calls(d)
    assert call['cwd'] == str(d.resolve())
    assert call['temp_existed'] is False
    assert call['argv'][0] == '--artifactory-only' and call['argv'][2:4] == ['-p', str(apk)]
    assert not os.listdir(tmproot)


def test_exit_3_returns_unsupported(tmp_path, tmproot, apk):
    make_fake_patcher(tmp_path, 'FakePatcher', exit=3)
    record, supported = run_artifactory_only(tmp_path, APP, apk)
    assert record == SAMPLE_RECORD and supported is False
    assert not os.listdir(tmproot)


def test_other_exit_raises_with_output_tail(tmp_path, tmproot, apk):
    lines = [f'line {i}' for i in range(100)]
    make_fake_patcher(tmp_path, 'FakePatcher', exit=1, print_lines=lines, stderr_line='boom', record=None)
    with pytest.raises(RunnerError) as e:
        run_artifactory_only(tmp_path, APP, apk)
    msg = str(e.value)
    assert 'line 99' in msg and 'boom' in msg and 'line 61' in msg
    assert 'line 60\n' not in msg + '\n'
    assert not os.listdir(tmproot)


def test_timeout_kills_and_raises(tmp_path, tmproot, apk):
    make_fake_patcher(tmp_path, 'FakePatcher', sleep=30, print_lines=['started'])
    with pytest.raises(RunnerError) as e:
        run_artifactory_only(tmp_path, APP, apk, timeout=1)
    assert 'timed out' in str(e.value).lower() and 'started' in str(e.value)
    assert not os.listdir(tmproot)


def test_missing_out_raises(tmp_path, tmproot, apk):
    make_fake_patcher(tmp_path, 'FakePatcher', record=None, print_lines=['hello'])
    with pytest.raises(RunnerError) as e:
        run_artifactory_only(tmp_path, APP, apk)
    assert 'hello' in str(e.value)
    assert not os.listdir(tmproot)


def test_invalid_json_raises(tmp_path, tmproot, apk):
    make_fake_patcher(tmp_path, 'FakePatcher', record=None, raw_out='{not json')
    with pytest.raises(RunnerError):
        run_artifactory_only(tmp_path, APP, apk)
    assert not os.listdir(tmproot)


def test_behavior_can_change_between_runs(tmp_path, tmproot, apk):
    d = make_fake_patcher(tmp_path, 'FakePatcher')
    assert run_artifactory_only(tmp_path, APP, apk)[1] is True
    set_behavior(d, exit=3, record=SAMPLE_RECORD)
    assert run_artifactory_only(tmp_path, APP, apk)[1] is False
    assert len(calls(d)) == 2

import smtplib

import pytest

from artifacts import alerts
from artifacts.state import AppState

PASSWORD = 'pw-do-not-leak-4471'
SMTP_VARS = ('SMTP_HOST', 'SMTP_PORT', 'SMTP_USERNAME', 'SMTP_PASSWORD',
             'MAIL_FROM', 'ALERT_EMAIL_TO')


class FakeSmtp:
    instances = []
    fail_on = None

    def __init__(self, host, port, **kw):
        self.kind = type(self).__name__
        self.host, self.port, self.kw = host, port, kw
        self.calls = []
        self.messages = []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _do(self, name, *args):
        if FakeSmtp.fail_on == name:
            raise smtplib.SMTPException('boom from ' + name)
        self.calls.append(name)

    def starttls(self, **kw):
        self._do('starttls')

    def login(self, user, password):
        self._do('login')
        self.login_args = (user, password)

    def send_message(self, msg):
        self._do('send')
        self.messages.append(msg)


class FakeSsl(FakeSmtp):
    pass


class FakePlain(FakeSmtp):
    pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    for v in SMTP_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    FakeSmtp.instances = []
    FakeSmtp.fail_on = None
    monkeypatch.setattr(smtplib, 'SMTP_SSL', FakeSsl)
    monkeypatch.setattr(smtplib, 'SMTP', FakePlain)
    return tmp_path


def configure(monkeypatch, **extra):
    vals = dict(ALERT_EMAIL_TO='dev@example.com', SMTP_USERNAME='bot@example.com',
                SMTP_PASSWORD=PASSWORD)
    vals.update(extra)
    for k, v in vals.items():
        monkeypatch.setenv(k, v)


def log_text(tmp_path):
    return (tmp_path / 'alerts.log').read_text()


def test_prints_and_logs_without_smtp(env, capsys):
    alerts.notify('Broke', 'line1\nline2')
    assert 'ALERT: Broke' in capsys.readouterr().out
    line = log_text(env).splitlines()
    assert len(line) == 1 and 'Broke' in line[0] and 'line2' in line[0]
    assert line[0][:4].isdigit() and 'Z' in line[0].split()[0]
    assert FakeSmtp.instances == []


def test_log_dir_created(monkeypatch, tmp_path):
    for v in SMTP_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path / 'a' / 'b'))
    alerts.notify('S', 'B')
    assert (tmp_path / 'a' / 'b' / 'alerts.log').exists()


def test_sends_over_implicit_tls_on_465(env, monkeypatch, capsys):
    configure(monkeypatch)
    alerts.notify('Subj', 'the body')
    (s,) = FakeSmtp.instances
    assert s.kind == 'FakeSsl' and (s.host, s.port) == ('smtp.gmail.com', 465)
    assert s.login_args == ('bot@example.com', PASSWORD)
    (m,) = s.messages
    assert m['To'] == 'dev@example.com' and m['From'] == 'bot@example.com'
    assert m['Subject'] == 'Subj' and m.get_content().strip() == 'the body'
    assert 'starttls' not in s.calls
    out = capsys.readouterr()
    assert PASSWORD not in out.out + out.err + log_text(env)


def test_blank_port_counts_as_unset(env, monkeypatch):
    configure(monkeypatch, SMTP_PORT='  ')
    alerts.notify('S', 'B')
    assert FakeSmtp.instances[0].port == 465


def test_starttls_on_other_port(env, monkeypatch):
    configure(monkeypatch, SMTP_PORT='587', SMTP_HOST='mail.example.com',
              MAIL_FROM='alerts@example.com')
    alerts.notify('S', 'B')
    (s,) = FakeSmtp.instances
    assert s.kind == 'FakePlain' and (s.host, s.port) == ('mail.example.com', 587)
    assert s.calls == ['starttls', 'login', 'send']
    assert s.messages[0]['From'] == 'alerts@example.com'


@pytest.mark.parametrize('missing', ['ALERT_EMAIL_TO', 'SMTP_USERNAME', 'SMTP_PASSWORD'])
def test_no_email_when_incomplete(env, monkeypatch, missing):
    configure(monkeypatch)
    monkeypatch.delenv(missing)
    alerts.notify('S', 'B')
    assert FakeSmtp.instances == []
    assert 'S' in log_text(env)


def test_no_email_when_host_blank(env, monkeypatch):
    configure(monkeypatch, SMTP_HOST='')
    alerts.notify('S', 'B')
    assert FakeSmtp.instances == []


@pytest.mark.parametrize('stage', ['login', 'send', 'starttls'])
def test_smtp_failure_swallowed_and_logged(env, monkeypatch, capsys, stage):
    configure(monkeypatch, SMTP_PORT='587')
    FakeSmtp.fail_on = stage
    alerts.notify('S', 'B')
    out = capsys.readouterr()
    text = out.out + out.err + log_text(env)
    assert 'boom from ' + stage in log_text(env)
    assert PASSWORD not in text


def test_connect_failure_swallowed(env, monkeypatch):
    configure(monkeypatch)

    def refuse(*a, **k):
        raise OSError('connection refused')
    monkeypatch.setattr(smtplib, 'SMTP_SSL', refuse)
    alerts.notify('S', 'B')
    assert 'connection refused' in log_text(env)


def test_subject_newlines_flattened_in_header(env, monkeypatch):
    configure(monkeypatch)
    alerts.notify('a\nBcc: x@y.z', 'B')
    assert '\n' not in FakeSmtp.instances[0].messages[0]['Subject']


def test_once_sends_then_suppresses_then_resends_on_change(env):
    st = AppState()
    assert alerts.once(st, 'k', 'Subj A', 'body') is True
    assert st.alerted == {'k': 'Subj A'}
    assert alerts.once(st, 'k', 'Subj A', 'body') is False
    assert alerts.once(st, 'k', 'Subj B', 'body') is True
    assert st.alerted['k'] == 'Subj B'
    assert alerts.once(st, 'other', 'Subj B', 'body') is True
    assert log_text(env).count('Subj') == 3

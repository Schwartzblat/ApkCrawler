"""Alert the developer about patching problems: stdout, a log file, optional email.

Email uses the same SMTP_* / MAIL_FROM settings as the server (one .env serves
both) and is sent only when ALERT_EMAIL_TO and a complete SMTP config are set.
Everything is read from the environment at call time. SMTP failures are logged,
never raised.
"""
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from artifacts.state import AppState

DEFAULT_ARTIFACTS_DIR = '~/.local/share/androidmod-crawler'


def _one_line(text: str) -> str:
    return ' '.join(str(text).split())


def _log(line: str) -> None:
    directory = Path(os.environ.get('ARTIFACTS_DIR') or DEFAULT_ARTIFACTS_DIR).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(directory / 'alerts.log', 'a', encoding='utf-8') as f:
        f.write(f'{stamp} {line}\n')


def _smtp_settings():
    """Return (to, host, port, user, password, sender), or None if email is off."""
    to = os.environ.get('ALERT_EMAIL_TO', '').strip()
    host = os.environ.get('SMTP_HOST', 'smtp.gmail.com').strip()
    user = os.environ.get('SMTP_USERNAME', '').strip()
    password = os.environ.get('SMTP_PASSWORD', '')
    sender = os.environ.get('MAIL_FROM', '').strip() or user
    if not (to and host and user and password and sender):
        return None
    raw_port = os.environ.get('SMTP_PORT', '').strip()
    port = int(raw_port) if raw_port else 465
    return to, host, port, user, password, sender


def _send_email(settings, subject: str, body: str) -> None:
    to, host, port, user, password, sender = settings
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = to
    msg['Subject'] = _one_line(subject)
    msg.set_content(body)
    context = ssl.create_default_context()  # verifies certificate and hostname
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    with server:
        if port != 465:
            server.starttls(context=context)
        server.login(user, password)
        server.send_message(msg)


def notify(subject: str, body: str) -> None:
    print(f'ALERT: {subject}')
    _log(f'{_one_line(subject)} | {_one_line(body)}')
    try:
        settings = _smtp_settings()
        if settings:
            _send_email(settings, subject, body)
    except Exception as e:  # never let a mail problem break the pipeline
        password = os.environ.get('SMTP_PASSWORD', '')
        reason = f'{type(e).__name__}: {e}'
        if password:
            reason = reason.replace(password, '***')
        message = f'alert email failed: {_one_line(reason)}'
        print(message)
        try:
            _log(message)
        except OSError:
            pass


def once(state: AppState, key: str, subject: str, body: str) -> bool:
    """Alert unless this key was already alerted with the same subject.

    Mutates state.alerted; the caller saves state.
    """
    if state.alerted.get(key) == subject:
        return False
    notify(subject, body)
    state.alerted[key] = subject
    return True

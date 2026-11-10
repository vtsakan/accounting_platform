"""Explicit recovery-mail boundary: private local capture or opted-in SMTP."""
import logging
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage, get_connection

logger = logging.getLogger(__name__)


def public_origin(value, allowed_hosts, *, production=False):
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in ({"https"} if production else {"http", "https"})
                 and parsed.hostname in allowed_hosts and not parsed.username and not parsed.password
                 and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                 and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        valid = False
    if not valid:
        raise ImproperlyConfigured("AUTH_PUBLIC_ORIGIN must be an explicit allowed origin.")
    return value.rstrip("/")


def deliver(subject, body, destination):
    # This function never logs addresses, tokens, bodies or provider exceptions.
    mode = settings.AUTH_MAIL_MODE
    if mode == "disabled":
        return
    message = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [destination])
    try:
        if mode == "capture":
            root = Path(settings.AUTH_MAIL_CAPTURE_ROOT)
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
                raise ValueError("Private mail directory required")
            fd, filename = tempfile.mkstemp(prefix="recovery-", suffix=".eml", dir=root)
            with os.fdopen(fd, "wb") as stream:
                stream.write(message.message().as_bytes())
        elif mode == "test":  # Only test.py selects this; production rejects it.
            message.connection = get_connection("django.core.mail.backends.locmem.EmailBackend")
            message.send()
        elif mode == "smtp" and settings.AUTH_MAIL_LIVE_ENABLED:
            message.connection = get_connection("django.core.mail.backends.smtp.EmailBackend")
            message.send()
        else:
            raise ValueError("Recovery mail adapter is not enabled")
    except Exception as error:
        # Same public acknowledgement for every outcome, including provider failure.
        logger.warning("Recovery mail delivery unavailable (%s); provider details omitted.", type(error).__name__)

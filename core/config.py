"""Small, explicit environment interface; never evaluates shell expressions."""

import os
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from core.redaction import register_secret


def load_local_env(path):
    """Load KEY=value lines for local development; process environment wins."""
    path = Path(path)
    if not path.is_file():
        return
    values = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise ImproperlyConfigured(f"Invalid or duplicate environment assignment at line {number}.")
        try:
            parts = shlex.split(value, comments=True, posix=True)
        except ValueError:
            raise ImproperlyConfigured(f"Invalid environment quoting at line {number}.") from None
        if len(parts) > 1:
            raise ImproperlyConfigured(f"Quote environment values containing spaces at line {number}.")
        values[key] = parts[0] if parts else ""
    for key, value in values.items():
        os.environ.setdefault(key, value)


def env(name, default=None, *, required=False, secret=False):
    direct = os.environ.get(name)
    filename = os.environ.get(name + "_FILE")
    if direct is not None and filename:
        raise ImproperlyConfigured(f"Set only one of {name} and {name}_FILE.")
    if filename:
        try:
            direct = Path(filename).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError):
            raise ImproperlyConfigured(f"Cannot read {name}_FILE.") from None
    value = default if direct is None else direct
    if required and (value is None or not str(value).strip()):
        raise ImproperlyConfigured(f"Required configuration missing: {name} or {name}_FILE.")
    if value is not None and ("\n" in str(value) or "\r" in str(value)):
        raise ImproperlyConfigured(f"{name} must be a single-line value.")
    if secret and value:
        register_secret(str(value))
    return value


def boolean(name, default=False):
    value = env(name)
    if value is None:
        return default
    if value.lower() not in {"true", "false", "1", "0"}:
        raise ImproperlyConfigured(f"{name} must be true/false or 1/0.")
    return value.lower() in {"true", "1"}


def integer(name, default, *, minimum=0, maximum=65535):
    try:
        value = int(env(name, str(default)))
    except (TypeError, ValueError):
        raise ImproperlyConfigured(f"{name} must be an integer.") from None
    if not minimum <= value <= maximum:
        raise ImproperlyConfigured(f"{name} is outside its permitted range.")
    return value


def hosts(required=False):
    value = env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]" if not required else None, required=required)
    result = [part.strip().lower() for part in value.split(",")]
    for host in result:
        valid = host == "[::1]" or re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
        if not valid or ".." in host:
            raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must contain explicit hostnames or IP addresses; wildcards and URLs are not allowed.")
    return result


def csrf_origins(allowed_hosts):
    value = env("DJANGO_CSRF_TRUSTED_ORIGINS", required=True)
    origins = [part.strip() for part in value.split(",")]
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            valid = (parsed.scheme == "https" and parsed.hostname in allowed_hosts and not parsed.username
                     and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment
                     and (parsed.port is None or 1 <= parsed.port <= 65535))
        except ValueError:
            valid = False
        if not valid:
            raise ImproperlyConfigured("DJANGO_CSRF_TRUSTED_ORIGINS must contain HTTPS origins matching allowed hosts.")
    return origins


def database(*, production=False):
    return {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", None if production else "accounting_platform", required=production),
        "USER": env("DB_USER", None if production else "accounting_platform", required=production),
        "PASSWORD": env("DB_PASSWORD", "" if not production else None, required=production, secret=True),
        "HOST": env("DB_HOST", None if production else "127.0.0.1", required=production),
        "PORT": str(integer("DB_PORT", 5432, minimum=1)),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"connect_timeout": 5},
    }}

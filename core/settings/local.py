"""Local-only .env loading. A generated .env provides stable local credentials."""

import os
from pathlib import Path
import secrets

from core.config import boolean, database, env, hosts, load_local_env
from core.redaction import register_secret

load_local_env(os.environ.get("DJANGO_ENV_FILE", Path(__file__).resolve().parents[2] / ".env"))
from .base import *  # noqa: E402,F403

DEBUG = boolean("DJANGO_DEBUG", True)
SECRET_KEY = env("DJANGO_SECRET_KEY", secret=True) or secrets.token_urlsafe(64)
register_secret(SECRET_KEY)
ALLOWED_HOSTS = hosts()
DATABASES = database()
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

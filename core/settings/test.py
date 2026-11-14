"""Isolated checks: never read the developer's .env and never fall back to SQLite."""

import secrets

from core.config import database
from core.redaction import register_secret
from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = secrets.token_urlsafe(64)
register_secret(SECRET_KEY)
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = database()
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
AUTH_MAIL_MODE = "test"
AUTH_PUBLIC_ORIGIN = "http://testserver"

"""Fail closed on missing deployment configuration; never load a local .env."""

from django.core.exceptions import ImproperlyConfigured

from core.config import boolean, csrf_origins, database, env, hosts, integer
from .base import *  # noqa: F403

if boolean("DJANGO_DEBUG", False):
    raise ImproperlyConfigured("Production requires DJANGO_DEBUG=false.")
DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY", required=True, secret=True)
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 8 or any(word in SECRET_KEY.lower() for word in ("change-me", "replace-me", "django-insecure")):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong generated key, not a placeholder.")
ALLOWED_HOSTS = hosts(required=True)
CSRF_TRUSTED_ORIGINS = csrf_origins(ALLOWED_HOSTS)
DATABASES = database(production=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = integer("DJANGO_HSTS_SECONDS", 3600, maximum=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# Enable only behind Caddy when it overwrites this header and Gunicorn is private.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if boolean("DJANGO_TRUST_PROXY_HEADERS", False) else None

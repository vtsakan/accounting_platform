"""Fail closed on missing deployment configuration; never load a local .env."""

from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

from core.config import boolean, csrf_origins, database, env, hosts, integer
from core.auth_mail import public_origin
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
# Only data-free internal probes bypass the HTTPS redirect. Public proxy/TLS
# behaviour is verified at S09; ordinary pages retain the redirect.
SECURE_REDIRECT_EXEMPT = [r"^health/live/$", r"^health/ready/$"]
SECURE_HSTS_SECONDS = integer("DJANGO_HSTS_SECONDS", 3600, maximum=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# Enable only behind Caddy when it overwrites this header and Gunicorn is private.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if boolean("DJANGO_TRUST_PROXY_HEADERS", False) else None
STATIC_ROOT = Path(env("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles")))
MEDIA_ROOT = Path(env("DJANGO_MEDIA_ROOT", "/app/media"))
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"}}

# SMTP remains disabled until a real provider and sender have been reviewed.
AUTH_PUBLIC_ORIGIN = public_origin(env("AUTH_PUBLIC_ORIGIN", "https://" + ALLOWED_HOSTS[0]), ALLOWED_HOSTS, production=True)
AUTH_MAIL_MODE = env("AUTH_MAIL_MODE", "disabled")
AUTH_MAIL_LIVE_ENABLED = boolean("AUTH_MAIL_LIVE_ENABLED", False)
AUTH_STAFF_MAIL_LIVE_ENABLED = boolean("AUTH_STAFF_MAIL_LIVE_ENABLED", False)
if AUTH_STAFF_MAIL_LIVE_ENABLED and not (AUTH_MAIL_MODE == "smtp" and AUTH_MAIL_LIVE_ENABLED):
    raise ImproperlyConfigured("Staff mail requires the explicit SMTP opt-in and a reviewed staff-mail scope.")
if AUTH_MAIL_MODE not in {"disabled", "smtp"} or (AUTH_MAIL_MODE == "smtp" and not AUTH_MAIL_LIVE_ENABLED):
    raise ImproperlyConfigured("Production recovery mail requires disabled mode or explicit SMTP opt-in.")
if AUTH_MAIL_MODE == "smtp":
    EMAIL_HOST = env("EMAIL_HOST", required=True)
    EMAIL_PORT = integer("EMAIL_PORT", 587, minimum=1)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", required=True)
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", required=True, secret=True)
    EMAIL_USE_TLS = True
    EMAIL_TIMEOUT = 10
    DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", required=True)

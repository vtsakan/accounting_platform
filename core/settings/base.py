"""Common configuration. Environment profiles supply secrets and database values."""

from pathlib import Path

from core.redaction import logging_config

BASE_DIR = Path(__file__).resolve().parents[2]
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "django_otp", "accounting",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware", "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "accounting.middleware.ActiveOfficeMiddleware",
    "accounting.auth_middleware.StaffSecurityMiddleware",
    "accounting.capabilities.OfficeCapabilityMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "core.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request",
                                         "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]},
}]
WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"
# Retain Django's existing auth.User; no custom user migration.
AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation." + name} for name in (
    "UserAttributeSimilarityValidator", "MinimumLengthValidator", "CommonPasswordValidator", "NumericPasswordValidator")]
LANGUAGE_CODE = "el"
LANGUAGES = [("el", "Ελληνικά")]
TIME_ZONE = "Europe/Athens"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True
FORMAT_MODULE_PATH = "core.formats"
LOCALE_PATHS = [BASE_DIR / "locale"]
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
LOGIN_URL = "/login/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
DEFAULT_EXCEPTION_REPORTER_FILTER = "core.redaction.RedactingExceptionReporterFilter"
CSRF_FAILURE_VIEW = "core.error_views.csrf_failure"
LOGGING = logging_config()

# S13 initial security defaults; no Redis/worker or live-mail provider required.
PASSWORD_RESET_TIMEOUT = 3600
AUTH_IDLE_SECONDS = 1800
AUTH_ABSOLUTE_SECONDS = 28800
AUTH_REAUTH_SECONDS = 300
AUTH_MFA_PENDING_SECONDS = 600
AUTH_RATE_WINDOW_SECONDS = 900
AUTH_RATE_LIMITS = {"login": (10, 100), "reset": (3, 50), "mfa": (20, 200), "manage": (10, 100)}
AUTH_RATE_LIMITS.update({"join": (10, 100), "office-manage": (30, 200)})
SESSION_COOKIE_AGE = AUTH_ABSOLUTE_SECONDS
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
AUTH_MAIL_MODE = "disabled"
AUTH_MAIL_LIVE_ENABLED = False
AUTH_STAFF_MAIL_LIVE_ENABLED = False
STAFF_INVITATION_SECONDS = 86400
OWNERSHIP_HANDOVER_SECONDS = 604800
AUTH_PUBLIC_ORIGIN = "http://localhost:8000"
AUTH_MAIL_CAPTURE_ROOT = "/tmp/accounting-auth-mail"
DEFAULT_FROM_EMAIL = "Λογιστική πλατφόρμα <noreply@example.invalid>"

"""Static collection only: no real runtime key and no usable database backend."""

import os
from pathlib import Path
import secrets

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = secrets.token_urlsafe(64)
ALLOWED_HOSTS = []
DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles")))
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"}}

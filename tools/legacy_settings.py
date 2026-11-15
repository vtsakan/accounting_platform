"""Only imported in operator-created, marked S25 containers; never an app profile."""
import os
import re
from django.core.exceptions import ImproperlyConfigured
from core.config import database
from core.settings.base import *  # noqa: F403

_nonce = os.environ.get('S25_NONCE', '')
if not re.fullmatch(r'[a-f0-9]{20}', _nonce) or os.environ.get('DB_NAME') not in {
        's25_source_' + _nonce, 's25_raw_' + _nonce, 's25_target_' + _nonce}:
    raise ImproperlyConfigured('S25 requires its isolated, explicitly named databases.')
SECRET_KEY = os.environ['S25_SIGNING_KEY']
DATABASES = database()
DEBUG = False
ALLOWED_HOSTS = ['testserver']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
AUTH_MAIL_MODE = 'disabled'
AUTH_PUBLIC_ORIGIN = 'http://testserver'
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}

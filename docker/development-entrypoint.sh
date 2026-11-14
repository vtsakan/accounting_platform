#!/bin/sh
set -eu
# Development only: apply the preserved, version-controlled migration history.
# No fixtures, database dumps or real client data are imported at startup.
python manage.py migrate --noinput
exec "$@"

#!/bin/sh
set -eu
# Database migration, fixture import and static export are explicit release
# operations. This entrypoint also supports future workers and management jobs.
exec "$@"

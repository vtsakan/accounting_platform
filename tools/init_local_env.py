#!/usr/bin/env python3
"""Create a local .env with generated credentials; never overwrite or print them."""

import os
from pathlib import Path
import secrets


def create_local_env(path):
    content = "\n".join([
        "# Local development only; keep this file out of Git.",
        "DJANGO_DEBUG=true", "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,[::1]",
        "DJANGO_SECRET_KEY=" + secrets.token_urlsafe(64),
        "DB_NAME=accounting_platform", "DB_USER=accounting_platform",
        "DB_PASSWORD=" + secrets.token_urlsafe(32), "DB_HOST=127.0.0.1", "DB_PORT=5432", "",
    ])
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
        stream.write(content)


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / ".env"
    try:
        create_local_env(path)
    except FileExistsError:
        raise SystemExit(".env already exists; no changes made.") from None
    print("Created .env with generated local credentials and owner-only permissions.")

"""Production WSGI defaults; Caddy/proxy target is configured at S09."""

from core.config import integer
from core.redaction import logging_config

bind = "0.0.0.0:8000"
wsgi_app = "core.wsgi:application"
workers = integer("GUNICORN_WORKERS", 2, minimum=1, maximum=16)
worker_class = "sync"
timeout = 30
graceful_timeout = 30
worker_tmp_dir = "/tmp"
control_socket_disable = True
umask = 0o077
preload_app = False
reload = False
accesslog = "-"
errorlog = "-"
# Exclude queries, cookies, authorisation, referrers and user-agent headers.
access_log_format = "%(h)s %(m)s %(U)s %(s)s %(L)s"
forwarded_allow_ips = "127.0.0.1,::1"
secure_scheme_headers = {"X-FORWARDED-PROTO": "https"}
logconfig_dict = logging_config()
for name in ("gunicorn.error", "gunicorn.access"):
    logconfig_dict["loggers"][name] = {"handlers": ["console"], "level": "INFO", "propagate": False}

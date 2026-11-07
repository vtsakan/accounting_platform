"""Redact configured secrets and common credential syntax at log/error boundaries."""

import json
import logging
import os
import re
from urllib.parse import quote

from django.views.debug import SafeExceptionReporterFilter

_registered = set()
_sensitive_key = re.compile(r"password|passwd|secret|token|authorization|cookie|credential|api[_-]?key|sessionid", re.I)
_assignment = re.compile(
    r'''(?i)(["']?(?:[\w-]*(?:password|passwd|secret|token|api[_-]?key|credential|sessionid|authorization|cookie)[\w-]*)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;&}\]]+)'''
)


def register_secret(value):
    if value:
        _registered.add(value)


def redact_text(value):
    text = str(value)
    known = set(_registered)
    known.update(v for k, v in os.environ.items() if _sensitive_key.search(k) and len(v) >= 4 and not k.endswith("_FILE"))
    variants = {variant for item in known for variant in (item, quote(item, safe=""), json.dumps(item)[1:-1])}
    for item in sorted(variants, key=len, reverse=True):
        text = text.replace(item, "[REDACTED]")
    text = re.sub(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", text)
    text = re.sub(r"(?im)((?:authorization|cookie|set-cookie)\s*:\s*)[^\r\n]+", r"\1[REDACTED]", text)
    return _assignment.sub(r"\1[REDACTED]", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        return redact_text(super().format(record))


class RedactingExceptionReporterFilter(SafeExceptionReporterFilter):
    def cleanse_setting(self, key, value):
        if _sensitive_key.search(str(key)):
            return self.cleansed_substitute
        cleaned = super().cleanse_setting(key, value)
        return redact_text(cleaned) if isinstance(cleaned, str) else cleaned

    def get_post_parameters(self, request):
        data = super().get_post_parameters(request).copy()
        for key in data:
            if _sensitive_key.search(key):
                data[key] = self.cleansed_substitute
        return data


def logging_config():
    return {
        "version": 1, "disable_existing_loggers": False,
        "formatters": {"safe": {"()": "core.redaction.RedactingFormatter", "format": "{levelname} {name}: {message}", "style": "{"}},
        "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "safe"}},
        "root": {"handlers": ["console"], "level": "INFO"},
        "loggers": {name: {"handlers": ["console"], "level": "INFO", "propagate": False}
                    for name in ("django", "django.request", "django.server", "django.security")},
    }

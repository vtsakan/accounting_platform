"""Quiet internal readiness probe; set HEALTHCHECK_HOST to an allowed hostname."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    request = Request("http://127.0.0.1:8000/health/ready/",
                      headers={"Host": os.environ.get("HEALTHCHECK_HOST", "127.0.0.1")})
    try:
        with urlopen(request, timeout=8) as response:
            return 0 if response.status == 200 and json.load(response) == {"status": "ready"} else 1
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Actual HTTP/TLS checks shared by native proof and the public S09 gate."""

import hashlib
from http.cookiejar import CookieJar
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from cloud import require


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(opener, url, *, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with opener.open(req, timeout=20) as response:
            return response.status, response.read(), response.headers, response.url
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers, error.url


def csrf(html):
    match = re.search(rb'name=[\"\']csrfmiddlewaretoken[\"\'][^>]*value=[\"\']([^\"\']+)', html)
    require(match, "Login form CSRF token missing")
    return match[1].decode()


def check_web(https, http, credentials, static_path, static_digest, context=None, redirect_https=None):
    context = context or ssl.create_default_context()
    no_redirect = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPSHandler(context=context))
    status, _, headers, _ = request(no_redirect, http + "/login/", headers={"X-Forwarded-Proto": "https"})
    require(status in {301, 302, 307, 308} and headers["Location"] == (redirect_https or https) + "/login/", "HTTP must redirect to the exact HTTPS hostname")
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(jar))
    status, body, headers, _ = request(opener, https + "/login/", headers={"Accept-Language": "en", "X-Forwarded-Proto": "http"})
    require(status == 200 and 'Σύνδεση'.encode() in body and b'lang="el"' in body, "Greek HTTPS login failed or proxy redirect loop")
    require(headers.get("Strict-Transport-Security") == "max-age=3600", "Preview HSTS policy differs")
    require(any(cookie.name == "csrftoken" and cookie.secure for cookie in jar), "Secure CSRF cookie missing")
    token = csrf(body)
    values = {**credentials, "csrfmiddlewaretoken": token}
    # A valid token with an untrusted origin must fail independently of login.
    status, foreign, _, _ = request(opener, https + "/login/", data=urllib.parse.urlencode(values).encode(), headers={"Origin": "https://untrusted.example.invalid", "Referer": https + "/login/"})
    require(status == 403 and 'Η ενέργεια δεν επιτρέπεται'.encode() in foreign, "Foreign-origin POST was not safely denied in Greek")
    status, _, _, _ = request(opener, https + "/login/", data=urllib.parse.urlencode(credentials).encode(), headers={"Origin": https, "Referer": https + "/login/"})
    require(status == 403, "Missing CSRF token was accepted")
    status, body, _, _ = request(opener, https + "/login/", data=urllib.parse.urlencode(values).encode(), headers={"Origin": https, "Referer": https + "/login/"})
    require(status == 200 and 'Αποσύνδεση'.encode() in body, "Valid login POST/session failed")
    require(any(cookie.name == "sessionid" and cookie.secure and cookie.has_nonstandard_attr("HttpOnly") for cookie in jar), "Secure HttpOnly session cookie missing")
    status, admin, _, _ = request(opener, https + "/admin/login/", headers={"Accept-Language": "en"})
    require(status == 200 and 'Σύνδεση'.encode() in admin, "Greek admin login failed")
    status, asset, headers, _ = request(opener, https + static_path, headers={"Accept-Encoding": "identity"})
    require(status == 200 and headers.get("Content-Type", "").startswith("text/css"), "Hashed static CSS failed")
    require("sha256:" + hashlib.sha256(asset).hexdigest() == static_digest, "Served static bytes differ from the image export")
    status, body, _, _ = request(opener, https + "/media/s09-private-canary.txt")
    require(status == 404 and 'διαθέσιμη'.encode() in body, "Direct media access must be blocked in Greek")
    status, body, _, _ = request(opener, https + "/health/ready/")
    require(status == 200 and b'"ready"' in body, "HTTPS readiness failed")
    return {"http_redirect": True, "certificate_trust": True, "greek_login_admin": True,
            "proxy_spoofing_and_no_redirect_loop": True, "valid_login_post": True,
            "foreign_origin_denied": True, "missing_csrf_denied": True,
            "secure_session_and_csrf_cookies": True, "one_hour_host_only_hsts": True, "static_image_bytes_match": True,
            "private_media_denied": True, "https_readiness": True}


def certificate(hostname):
    with socket.create_connection((hostname, 443), timeout=15) as connection:
        with ssl.create_default_context().wrap_socket(connection, server_hostname=hostname) as secured:
            certificate = secured.getpeercert()
            fingerprint = "sha256:" + hashlib.sha256(secured.getpeercert(binary_form=True)).hexdigest()
    return {"fingerprint": fingerprint, "not_after": certificate["notAfter"], "chain_trusted_and_hostname_verified": True}


def private_ports(ip):
    result = {}
    for port in (5432, 8000):
        try:
            with socket.create_connection((ip, port), timeout=3):
                raise ValueError("A private database/application port is reachable externally")
        except (socket.timeout, ConnectionRefusedError):
            result[str(port)] = "closed_or_filtered"
        except OSError as error:
            # Only an explicit timeout/refusal establishes this particular check.
            if error.errno not in {110, 111}:
                raise
            result[str(port)] = "closed_or_filtered"
    return result

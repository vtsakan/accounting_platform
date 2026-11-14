import json
import runpy
import secrets
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError, connection
from django.test import SimpleTestCase, TestCase, override_settings

from core.tests.test_s04 import ROOT, load_profile, production_env


class HealthEndpointTests(SimpleTestCase):
    def test_liveness_without_database_queries(self):
        response = self.client.get("/health/live/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_head_is_safe_and_empty(self):
        response = self.client.head("/health/live/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")

    def test_probes_reject_post(self):
        for path in ("/health/live/", "/health/ready/"):
            self.assertEqual(self.client.post(path).status_code, 405)

    def test_unapproved_host_is_rejected(self):
        for path in ("/health/live/", "/health/ready/"):
            self.assertEqual(self.client.get(path, HTTP_HOST="unapproved.example.invalid").status_code, 400)

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r"^health/live/$", r"^health/ready/$"])
    def test_only_exact_probe_paths_bypass_https(self):
        self.assertEqual(self.client.get("/health/live/").status_code, 200)
        self.assertEqual(self.client.get("/login/").status_code, 301)
        self.assertEqual(self.client.get("/health/live/extra/").status_code, 301)

    def test_database_failure_is_generic(self):
        marker = secrets.token_urlsafe(32)
        with patch("core.health.connection") as database:
            database.cursor.side_effect = OperationalError(marker)
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertNotIn(marker, response.content.decode())

    def test_probe_response_is_not_cacheable(self):
        response = self.client.get("/health/live/")
        self.assertIn("no-store", response.headers["Cache-Control"])


class ReadinessPostgreSQLTests(TestCase):
    def test_readiness_on_real_postgresql17(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertEqual(connection.pg_version // 10000, 17)
        response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})


class ProductionBuildTests(SimpleTestCase):
    def test_static_build_has_no_usable_database(self):
        code = "import django,json;django.setup();from django.conf import settings;print(json.dumps([settings.DEBUG,settings.DATABASES['default']['ENGINE']]))"
        result = load_profile("build", code=code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [False, "django.db.backends.dummy"])

    def test_production_uses_manifest_static_and_exact_probe_exemptions(self):
        code = "import django,json;django.setup();from django.conf import settings;print(json.dumps([settings.STORAGES['staticfiles']['BACKEND'],settings.SECURE_REDIRECT_EXEMPT]))"
        result = load_profile("production", production_env(), code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
                                                    [r"^health/live/$", r"^health/ready/$"]])

    def test_gunicorn_access_format_excludes_queries_and_headers(self):
        with patch.dict("os.environ", {"GUNICORN_WORKERS": "2"}):
            config = runpy.run_path(str(ROOT / "gunicorn.conf.py"))
        self.assertEqual(config["access_log_format"], "%(h)s %(m)s %(U)s %(s)s %(L)s")
        self.assertFalse(config["reload"])
        self.assertTrue(config["control_socket_disable"])
        self.assertIn("gunicorn.error", config["logconfig_dict"]["loggers"])

    def test_invalid_worker_count_fails_closed(self):
        with patch.dict("os.environ", {"GUNICORN_WORKERS": "0"}):
            with self.assertRaises(ImproperlyConfigured):
                runpy.run_path(str(ROOT / "gunicorn.conf.py"))

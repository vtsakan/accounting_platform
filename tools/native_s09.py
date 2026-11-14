#!/usr/bin/env python3
"""Actual local Caddy/TLS/Gunicorn/PostgreSQL proof; cannot mark S09 Verified."""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import ssl
import subprocess
import tempfile
import time
from zoneinfo import ZoneInfo

import preview_common as common
from cloud import require
from preview_host import PERSISTENCE_CODE
import preview_http
from verify_s05 import HIDDEN_VALUES, run
from verify_s06 import native_database


def port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def stop(process):
    if process and process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def verify(args):
    with tempfile.TemporaryDirectory(prefix="accounting-s09-native-") as temporary:
        directory = Path(temporary)
        with native_database(args.native_bin, directory) as (base, version):
            environment = {**base, "DJANGO_SETTINGS_MODULE": "core.settings.test"}
            run([args.python, "manage.py", "test", "core.tests", "accounting.tests_integration", "accounting.tests_regressions",
                 "--testrunner=accounting.regression_runner.FinancialRegressionRunner", "--noinput"], environment=environment)
            suite = json.loads(Path(base["ACCOUNTING_REGRESSION_REPORT"]).read_text())
            require(suite["known_failures_reproduced"] == 26 and all(suite[k] == 0 for k in ("unexpected_failures", "unexpected_errors", "unexpected_successes", "skips")), "Financial baseline differs")
            web_port, http_port, https_port = port(), port(), port()
            signing, password = secrets.token_urlsafe(64), secrets.token_urlsafe(64)
            HIDDEN_VALUES.update({signing, password})
            # Exercise non-superuser schema ownership/migrations on the real server.
            bootstrap = """import os,psycopg
from psycopg import sql
with psycopg.connect(dbname='postgres',user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],host=os.environ['DB_HOST'],port=os.environ['DB_PORT']) as c:
    c.execute(sql.SQL('CREATE ROLE accounting_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Literal(os.environ['S09_APP_PASSWORD'])))
    c.execute(sql.SQL('ALTER DATABASE {} OWNER TO accounting_app').format(sql.Identifier(os.environ['DB_NAME'])))
"""
            run([args.python, "-c", bootstrap], environment={**base, "S09_APP_PASSWORD": password})
            runtime = directory / "runtime"; runtime.mkdir(mode=0o700)
            for name, value in (("signing", signing), ("database", password)):
                p = runtime / name; p.write_text(value); p.chmod(0o400)
            env = {key: value for key, value in base.items() if key not in {"DB_PASSWORD", "DJANGO_SECRET_KEY"}}
            env.update(DJANGO_SETTINGS_MODULE="core.settings.production", DB_USER="accounting_app",
                       DB_PASSWORD_FILE=str(runtime / "database"), DJANGO_SECRET_KEY_FILE=str(runtime / "signing"),
                       DJANGO_ALLOWED_HOSTS="localhost", DJANGO_CSRF_TRUSTED_ORIGINS=f"https://localhost:{https_port}",
                       DJANGO_TRUST_PROXY_HEADERS="true", DJANGO_MEDIA_ROOT=str(directory / "private-media"),
                       DJANGO_STATIC_ROOT=str(directory / "static"))
            run([args.python, "manage.py", "migrate", "--noinput"], environment=env)
            credentials = {"username": "s09_native_probe", "password": secrets.token_urlsafe(32)}
            HIDDEN_VALUES.add(credentials["password"])
            create = "import django,os;django.setup();from django.contrib.auth import get_user_model;get_user_model().objects.create_user(username='s09_native_probe',password=os.environ['S09_LOGIN_VALUE'])"
            run([args.python, "-c", create], environment={**env, "S09_LOGIN_VALUE": credentials["password"]})
            before = json.loads(run([args.python, "-c", PERSISTENCE_CODE], environment={**env, "S09_CREATE_MARKERS": "1"}).stdout)
            static = directory / "static"
            run([args.python, "manage.py", "collectstatic", "--noinput", "--settings=core.settings.build"], environment={**env, "DJANGO_STATIC_ROOT": str(static)})
            require((static / "staticfiles.json").is_file(), "Separate static collection root missing")
            manifest = json.loads((static / "staticfiles.json").read_text())
            css = manifest["paths"]["admin/css/base.css"]
            config = (common.ROOT / "infrastructure/Caddyfile").read_text()
            config = config.replace("admin off", f"admin off\n\thttp_port {http_port}\n\thttps_port {https_port}\n\tlocal_certs\n\tskip_install_trust")
            config = config.replace("web:8000", f"127.0.0.1:{web_port}").replace("/srv/static", str(static))
            caddyfile = directory / "Caddyfile"; caddyfile.write_text(config)
            proxy_env = {**os.environ, "SITE_DOMAIN": "localhost", "ACME_EMAIL": "operator@example.invalid",
                         "XDG_DATA_HOME": str(directory / "data"), "XDG_CONFIG_HOME": str(directory / "config")}
            processes = []
            web_log = directory / "gunicorn.log"; proxy_log = directory / "proxy.log"
            marker = secrets.token_urlsafe(32)
            try:
                with web_log.open("wb") as web_output, proxy_log.open("wb") as proxy_output:
                    def start_web():
                        process = subprocess.Popen([str(args.python), "-m", "gunicorn", "--config", "gunicorn.conf.py", "--bind", f"127.0.0.1:{web_port}"], cwd=common.ROOT, env=env, stdout=web_output, stderr=web_output, start_new_session=True)
                        processes.append(process)
                        return process
                    web = start_web()
                    caddy = subprocess.Popen([str(args.caddy), "run", "--config", str(caddyfile), "--adapter", "caddyfile"], env=proxy_env, stdout=proxy_output, stderr=proxy_output, start_new_session=True)
                    processes.append(caddy)
                    roots = []
                    for _ in range(50):
                        roots = list((directory / "data").rglob("root.crt"))
                        if roots:
                            break
                        require(caddy.poll() is None and web.poll() is None, "Native server exited")
                        time.sleep(0.2)
                    require(len(roots) == 1, "Local test CA root missing")
                    context = ssl.create_default_context(cafile=str(roots[0]))
                    https, http = f"https://localhost:{https_port}", f"http://localhost:{http_port}"
                    ready = False
                    for _ in range(50):
                        try:
                            status, _, _, _ = preview_http.request(preview_http.urllib.request.build_opener(preview_http.urllib.request.ProxyHandler({}), preview_http.urllib.request.HTTPSHandler(context=context)), https + "/health/ready/")
                            if status == 200:
                                ready = True; break
                        except OSError:
                            pass
                        time.sleep(0.2)
                    require(ready, "Native proxy did not become ready")
                    # Caddy's global port options change the test listeners, while
                    # its public redirect still targets the standard HTTPS port.
                    checks = preview_http.check_web(https, http, credentials, "/static/" + css, common.file_sha(static / css), context, redirect_https="https://localhost")
                    stop(web)
                    opener = preview_http.urllib.request.build_opener(preview_http.urllib.request.ProxyHandler({}), preview_http.urllib.request.HTTPSHandler(context=context))
                    status, body, _, _ = preview_http.request(opener, https + "/login/?token=" + marker, headers={"Authorization": "Bearer " + marker, "Cookie": "private=" + marker})
                    require(status == 502 and 'υπηρεσία'.encode() in body, "Proxy failure response is not safe Greek")
                    require(marker not in proxy_log.read_text() and marker not in web_log.read_text(), "Request canary leaked into logs")
                    web = start_web()
                    time.sleep(0.5)
                    after = json.loads(run([args.python, "-c", PERSISTENCE_CODE], environment=env).stdout)
                    require(before == after, "Synthetic data did not persist across process restart")
                    # Missing data must fail a check rather than being recreated.
                    delete = "import django;django.setup();from accounting.models import Entity;Entity.objects.filter(vat_number='000000000').delete()"
                    run([args.python, "-c", delete], environment=env)
                    lost = subprocess.run([str(args.python), "-c", PERSISTENCE_CODE], cwd=common.ROOT, env=env, capture_output=True)
                    require(lost.returncode != 0, "Persistence checker recreated missing data")
            finally:
                for process in reversed(processes):
                    stop(process)
            return {"step": "S09", "status": "Prepared", "verified_at": datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
                    "mode": "native-caddy-internal-ca-gunicorn-postgresql17", "postgresql": version,
                    "suite": {key: suite[key] for key in ("tests_run", "tests_passed", "known_failures_reproduced", "unexpected_failures", "unexpected_errors", "unexpected_successes", "skips")},
                    "proxy_checks": checks, "greek_proxy_failure": True, "request_canary_excluded_from_logs": True,
                    "restricted_application_role_migrations": True, "synthetic_process_restart_persistence": True,
                    "missing_marker_denied_without_recreation": True, "docker_execution": False,
                    "public_acme_issuance_tested": False, "vm_reboot_tested": False, "off_vm_restore_tested": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-bin", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--caddy", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))

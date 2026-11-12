#!/usr/bin/env python3
"""Check the committed Caddy header rules on disposable loopback HTTP listeners."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from threading import Thread
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.referrer import referrer_policy
from types import SimpleNamespace


def check(binary):
    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("/unavailable/"):
                self.close_connection = True
                return
            self.send_response(200)
            if self.path != "/without-header/":
                self.send_header("Referrer-Policy", referrer_policy(SimpleNamespace(path_info=self.path)))
            self.end_headers(); self.wfile.write(b"synthetic referrer fixture")

        def log_message(self, *args):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = Thread(target=backend.serve_forever, daemon=True); thread.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
    try:
        with tempfile.TemporaryDirectory(prefix="s14-referrer-proxy-") as temporary:
            directory = Path(temporary)
            source = (ROOT / "infrastructure/Caddyfile").read_text()
            source = source.rsplit("\nhttp:// {", 1)[0]  # No public/default-port listener in this fixture.
            source = source.replace("{$SITE_DOMAIN}", "http://127.0.0.1:"+str(port))
            source = source.replace("web:8000", "127.0.0.1:"+str(backend.server_port))
            config = directory / "Caddyfile"; config.write_text(source)
            environment = {**os.environ, "ACME_EMAIL":"synthetic@example.invalid", "XDG_DATA_HOME":str(directory/"data"), "XDG_CONFIG_HOME":str(directory/"config")}
            adapted = subprocess.run([str(binary), "adapt", "--config", str(config), "--adapter", "caddyfile", "--validate"],
                env=environment, capture_output=True, text=True)
            if adapted.returncode:
                raise RuntimeError("Caddy fixture validation failed: "+adapted.stderr[-2000:])
            with (directory/"proxy.log").open("w+") as log:
                process = subprocess.Popen([str(binary), "run", "--config", str(config), "--adapter", "caddyfile"], env=environment, stdout=log, stderr=log)
                try:
                    base = "http://127.0.0.1:"+str(port)
                    for attempt in range(50):
                        try:
                            with urlopen(base+"/without-header/", timeout=1):
                                break
                        except URLError:
                            if process.poll() is not None:
                                raise RuntimeError("Caddy fixture exited before becoming ready")
                            time.sleep(.1)
                    cases = {
                        "/login/":"same-origin", "/auth/mfa/setup/":"same-origin", "/office/settings/":"same-origin",
                        "/join/demo/":"same-origin", "/join/demo/synthetic-canary/":"no-referrer",
                        "/auth/password/reset/uid/synthetic-canary/":"no-referrer",
                        "/auth/password/reset/uid/set-password/":"same-origin",
                        "/without-header/":"same-origin", "/join/demo/unavailable/":"no-referrer",
                    }
                    for path, expected in cases.items():
                        try:
                            response = urlopen(base+path, timeout=3)
                        except HTTPError as error:
                            response = error
                        with response:
                            if response.headers.get_all("Referrer-Policy") != [expected]:
                                raise RuntimeError("Incorrect proxy referrer policy for fixture route "+path+": "+str(response.headers.get_all("Referrer-Policy")))
                    return {"mode":"native-caddy-loopback-http", "status":"Passed", "route_checks":len(cases),
                        "form_origin_policy":True, "token_redirect_privacy":True, "default_does_not_overwrite_upstream":True,
                        "upstream_failure_token_privacy":True, "public_tls_or_cloud_execution":False}
                finally:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
    finally:
        backend.shutdown(); backend.server_close(); thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caddy", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.caddy), indent=2))

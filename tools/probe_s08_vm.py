#!/usr/bin/env python3
"""Optional S08 VM access replay. Uses metadata credentials; prints no secret values.

Run on the selected VM. A unique synthetic backup object remains for administrator
cleanup. Only anonymous probes accept 401; authenticated IAM denials require 403.
"""

import argparse
import base64
from datetime import datetime, timezone
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

CONTENT = b"Accounting S08 synthetic permissions probe.\n"


def status_matches(status, expected, authenticated):
    allowed = (expected,) if isinstance(expected, int) else tuple(expected)
    if authenticated and 401 in allowed:
        raise ValueError("Anonymous denial status set used for authenticated request")
    return status in allowed


class Probe:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.token = None
        self.results = []
        self.cleanup = []

    def metadata(self, path):
        request = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/" + path,
            headers={"Metadata-Flavor": "Google"},
        )
        with self.opener.open(request, timeout=20) as response:
            return response.read().decode().strip()

    def call(self, label, url, expected=200, method="GET", data=None, auth=True):
        headers = {"Authorization": f"Bearer {self.token}"} if auth else {}
        if isinstance(data, dict):
            headers["Content-Type"] = "application/json"
            data = json.dumps(data).encode()
        elif data is not None:
            headers["Content-Type"] = "application/octet-stream"
        request = urllib.request.Request(url, headers=headers, method=method, data=data)
        try:
            with self.opener.open(request, timeout=30) as response:
                status, body = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        matched = status_matches(status, expected, auth)
        self.results.append({"check": label, "http_status": status, "authenticated": auth, "passed": matched})
        if not matched:
            raise RuntimeError(f"{label}: HTTP {status}; expected {expected}")
        return body

    def run(self, config):
        from cloud import account, require, validate
        validate(config, config["project_id"])
        require(self.metadata("project/project-id") == config["project_id"], "Wrong project")
        require(self.metadata("instance/name") == config["vm_name"], "Wrong VM")
        require(self.metadata("instance/service-accounts/default/email") == account(config), "Wrong service account")
        self.token = json.loads(self.metadata("instance/service-accounts/default/token"))["access_token"]
        project = config["project_id"]
        for key, version_key in (("django_ref", "django"), ("postgres_ref", "postgres")):
            version = config["secret_versions"][version_key]
            require(type(version) is int and version > 0, "Pin a numeric secret version")
            resource = f"projects/{project}/secrets/{config[key]}/versions/{version}"
            result = json.loads(self.call(version_key + " secret read", f"https://secretmanager.googleapis.com/v1/{resource}:access"))
            value = base64.b64decode(result["payload"]["data"], validate=True)
            require(len(value) >= 50, "Unexpected generated secret length")
            del value, result
        self.call("project secret listing denied", f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets?pageSize=1", expected=403)
        repo = f"https://artifactregistry.googleapis.com/v1/projects/{project}/locations/{config['region']}/repositories/{config['repository']}"
        self.call("registry image listing", repo + "/dockerImages?pageSize=1")
        download = "artifactregistry.repositories.downloadArtifacts"
        permissions = json.loads(self.call("registry permissions", repo + ":testIamPermissions", method="POST", data={"permissions": [download, "artifactregistry.repositories.uploadArtifacts", "artifactregistry.repositories.deleteArtifacts", "artifactregistry.repositories.setIamPolicy"]})).get("permissions", [])
        require(set(permissions) == {download}, "Unexpected registry permissions")
        for kind, key in (("documents", "document_bucket"), ("backups", "backup_bucket")):
            bucket = config[key]
            name = f"s08-verification/{uuid.uuid4().hex}.txt"
            upload = f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?" + urllib.parse.urlencode({"uploadType": "media", "name": name})
            obj = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/" + urllib.parse.quote(name, safe="")
            listing = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o?" + urllib.parse.urlencode({"prefix": name, "maxResults": 1})
            info = json.loads(self.call(kind + " create", upload + "&ifGenerationMatch=0", method="POST", data=CONTENT))
            generation = info["generation"]
            cleanup = {"url": f"gs://{bucket}/{name}", "generation": generation}
            self.cleanup.append(cleanup)
            self.call(kind + " anonymous read blocked", obj + "?alt=media", expected=(401, 403), auth=False)
            if kind == "documents":
                require(self.call("document read", obj + "?alt=media") == CONTENT, "Document content mismatch")
                items = json.loads(self.call("document list", listing)).get("items", [])
                require(any(row.get("name") == name for row in items), "Document not listed")
                updated = json.loads(self.call("document overwrite", upload + f"&ifGenerationMatch={generation}", method="POST", data=CONTENT + b"Updated.\n"))
                generation = cleanup["generation"] = updated["generation"]
                require(self.call("updated document read", obj + "?alt=media") == CONTENT + b"Updated.\n", "Updated document mismatch")
                self.call("document delete", obj + f"?ifGenerationMatch={generation}", expected=204, method="DELETE")
                self.cleanup.remove(cleanup)
            else:
                self.call("backup VM read denied", obj + "?alt=media", expected=403)
                self.call("backup VM list denied", listing, expected=403)
                self.call("backup VM overwrite denied", upload + f"&ifGenerationMatch={generation}", expected=403, method="POST", data=CONTENT)
                self.call("backup VM delete denied", obj + f"?ifGenerationMatch={generation}", expected=403, method="DELETE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=argparse.FileType("r"), required=True)
    args = parser.parse_args()
    probe = Probe()
    success = False
    error = None
    try:
        probe.run(json.load(args.config))
        success = True
    except (ValueError, RuntimeError, KeyError, OSError) as exception:
        # No API response bodies, trace locals, tokens, or secret payloads.
        error = type(exception).__name__
    print(json.dumps({"step": "S08", "checked_at": datetime.now(timezone.utc).isoformat(),
                      "status": "Passed" if success else "Failed", "error_type": error,
                      "checks": probe.results, "administrator_cleanup": probe.cleanup,
                      "actual_docker_pull_tested": False, "application_deployment_tested": False}, indent=2))
    raise SystemExit(not success)


if __name__ == "__main__":
    main()

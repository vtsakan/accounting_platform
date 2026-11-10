#!/usr/bin/env python3
"""Operate the local S05 stack without printing resolved credentials."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def compose_environment():
    # Explicit env-file values define the local database; inherited production
    # settings must not override them through Compose interpolation.
    return {key: value for key, value in os.environ.items()
            if not key.startswith(("DB_", "DJANGO_", "COMPOSE_")) and key != "WEB_PORT"}


def require_local_docker():
    try:
        # DOCKER_CONTEXT overrides DOCKER_HOST in the Docker CLI.
        endpoint = None if os.environ.get("DOCKER_CONTEXT") else os.environ.get("DOCKER_HOST")
        if not endpoint:
            output = subprocess.check_output(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"], text=True)
            endpoint = json.loads(output)
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"unix", "npipe"} and not (
                parsed.scheme in {"tcp", "http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise RuntimeError("Select a local Docker context for S05; remote Docker endpoints are not used.")
        subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        raise RuntimeError("A running local Docker Engine and the Compose plugin are required.") from None


def compose_command(env_file=None, project=None):
    command = ["docker", "compose", "--project-directory", str(ROOT), "--file", str(ROOT / "docker-compose.yml"),
               "--env-file", str(env_file or ROOT / ".env")]
    if project:
        command += ["--project-name", project]
    return command


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "down", "migrate", "admin", "seed", "test", "test-raw", "logs", "status", "config"])
    parser.add_argument("--office", help="Explicit synthetic office UUID for seed")
    args = parser.parse_args()
    if args.action == "up" and not (ROOT / ".env").exists():
        from init_local_env import create_local_env
        create_local_env(ROOT / ".env")
        print("Created private local .env with generated credentials.", flush=True)
    operations = {
        "up": ["up", "--build", "--detach", "--wait", "--wait-timeout", "180"],
        "down": ["down"],
        "migrate": ["exec", "-T", "web", "python", "manage.py", "migrate", "--noinput"],
        "admin": ["exec", "web", "python", "manage.py", "createsuperuser"],
        "seed": ["exec", "-T", "web", "python", "manage.py", "seed_development_data"],
        "test": ["exec", "-T", "web", "python", "manage.py", "test", "core.tests", "accounting.tests_integration",
                 "accounting.tests_regressions", "accounting.tests_offices", "accounting.tests_ownership", "--settings=core.settings.test",
                 "--testrunner=accounting.regression_runner.FinancialRegressionRunner"],
        "test-raw": ["exec", "-T", "web", "python", "manage.py", "test", "accounting.tests_regressions",
                     "--settings=core.settings.test", "--testrunner=django.test.runner.DiscoverRunner"],
        "logs": ["logs", "--tail", "100", "web", "db"],
        "status": ["ps"],
        "config": ["config", "--quiet"],
    }
    if args.action == "seed":
        if not args.office:
            parser.error("seed requires --office with an explicit existing synthetic office UUID")
        operations["seed"] += ["--office", args.office]
    try:
        if args.action != "config":
            require_local_docker()
        subprocess.run(compose_command() + operations[args.action], cwd=ROOT, env=compose_environment(), check=True)
    except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError) as error:
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        raise SystemExit(1) from None

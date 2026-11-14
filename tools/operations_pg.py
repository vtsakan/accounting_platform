"""Consistent PG17 snapshot, logical fingerprints and bounded custom dumps."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time

from cloud import require
import operations_common as common

# Compare every public table, including migrations/auth data, in the exact
# snapshot used by pg_dump. MD5 here is a logical comparison, not authentication;
# the complete archive is authenticated by age and checked with SHA-256/CRC32C.
FINGERPRINT_SQL = r"""
SET TIME ZONE 'UTC';
SET extra_float_digits=3;
SET statement_timeout='120s';
SELECT format('SELECT json_build_object(''table'',%L,''rows'',count(*),''checksum'',md5(coalesce(string_agg(md5(to_jsonb(t)::text),'''' ORDER BY md5(to_jsonb(t)::text)),''''))) FROM %I.%I AS t;',
              schemaname || '.' || tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY tablename
\gexec
SELECT 'S10-END';
"""


def fingerprints(output):
    rows = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
    require(rows and len(rows) == len({row['table'] for row in rows}), "No tables or duplicate logical fingerprints")
    require(all(set(row) == {'table', 'rows', 'checksum'} and type(row['rows']) is int and row['rows'] >= 0
                and re.fullmatch(r'[0-9a-f]{32}', row['checksum']) for row in rows), "Malformed logical fingerprints")
    return sorted(rows, key=lambda row: row['table'])


@contextmanager
def snapshot(psql, environment=None):
    process = subprocess.Popen([str(v) for v in psql], env=environment, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    try:
        process.stdin.write(("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
                             "SELECT 'S10-SNAPSHOT:' || pg_export_snapshot();\n" + FINGERPRINT_SQL).encode())
        process.stdin.flush()
        output = bytearray()
        deadline = time.monotonic() + 150
        with selectors.DefaultSelector() as poller:
            poller.register(process.stdout, selectors.EVENT_READ)
            while not output.endswith(b'S10-END\n'):
                require(time.monotonic() < deadline and len(output) <= 4 * 1024 * 1024, "Snapshot query exceeded its budget")
                if not poller.select(timeout=min(1, max(0, deadline - time.monotonic()))):
                    require(process.poll() is None, "Snapshot query failed")
                    continue
                block = os.read(process.stdout.fileno(), 65536)
                require(block, "Snapshot query ended unexpectedly")
                output.extend(block)
        text = output.decode()
        found = re.findall(r'^S10-SNAPSHOT:([0-9A-F]{8}-[0-9A-F]{8}-[0-9A-F]+)$', text, re.M)
        require(len(found) == 1, "Invalid exported snapshot")
        yield found[0], fingerprints(text)
    finally:
        if process.poll() is None:
            try:
                process.stdin.write(b'ROLLBACK;\n\\q\n'); process.stdin.flush(); process.stdin.close()
                process.wait(timeout=10)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                process.kill(); process.wait(timeout=10)
        process.stdout.close()


def dump(psql, pg_dump, target, environment=None, max_bytes=common.MAX_DUMP, during_snapshot=None):
    # pg_dump writes stdout; parent enforces size without relying on container
    # rlimits or trusting a successful empty/truncated output file.
    started = common.now()
    with snapshot(psql, environment) as (identifier, expected):
        if during_snapshot:
            during_snapshot()  # Native proof mutates the source after export.
        with target.open('xb') as stream:
            process = subprocess.Popen([str(v) for v in pg_dump] + ['--format=custom', '--no-owner', '--no-acl',
                                       '--lock-wait-timeout=15s', '--snapshot=' + identifier],
                                       env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            total, deadline = 0, time.monotonic() + 300
            try:
                with selectors.DefaultSelector() as poller:
                    poller.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        require(time.monotonic() < deadline, 'Database dump timed out')
                        if not poller.select(timeout=1):
                            continue
                        block = os.read(process.stdout.fileno(), 1024 * 1024)
                        if not block:
                            break
                        total += len(block)
                        require(total <= max_bytes, 'Database dump exceeds the preview tmpfs budget')
                        stream.write(block)
                require(process.wait(timeout=10) == 0 and total > 100, 'Database dump failed or is empty')
            finally:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=10)
                process.stdout.close()
        target.chmod(0o600)
    with target.open('rb') as stream:
        require(stream.read(5) == b'PGDMP', 'Custom PostgreSQL archive signature missing')
    return {'snapshot_started_at': started, 'dump_sha256': common.sha(target), 'tables': expected}


def verify_tables(psql, expected, environment=None):
    actual = fingerprints(common.run(psql, payload=FINGERPRINT_SQL.encode(), environment=environment).decode())
    require(actual == expected, 'Restored table counts/content differ from the exported snapshot')
    return {'tables_checked': len(actual), 'rows_checked': sum(row['rows'] for row in actual), 'all_public_tables_match': True}


def restore_dump(command, path, environment=None):
    with path.open('rb') as stream:
        result = subprocess.run([str(v) for v in command] + ['--no-owner', '--no-acl', '--exit-on-error', '--single-transaction'],
                                stdin=stream, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
    require(result.returncode == 0, 'Isolated PostgreSQL restore failed; diagnostic payload omitted')

#!/usr/bin/env python3
"""Real local PG17/age snapshot and recovery proof; cannot verify GCP/Docker."""

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from cloud import require
import operations_common as common
from operations_host import encrypt
import operations_pg as pg
from operations_recovery import decrypt, plaintext_directory
import preview_common as preview
from verify_s06 import native_database


def verify(args):
    os.environ['PATH'] = str(args.age_bin.resolve()) + os.pathsep + os.environ.get('PATH', '')
    version = common.run(['age', '--version']).decode().strip()
    with tempfile.TemporaryDirectory(prefix='accounting-s10-native-') as temporary:
        root = Path(temporary)
        with native_database(args.native_bin, root) as (environment, pg_version):
            common.run([args.python, common.ROOT / 'manage.py', 'migrate', '--noinput'], environment=environment)
            psql = [args.native_bin / 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '--dbname=' + environment['DB_NAME']]
            pg_dump = [args.native_bin / 'pg_dump', '--dbname=' + environment['DB_NAME']]
            common.run(psql, payload="CREATE TABLE s10_recovery_case (id integer PRIMARY KEY, label text NOT NULL, amount numeric(12,2) NOT NULL); INSERT INTO s10_recovery_case VALUES (1,'Δοκιμή ανάκτησης',12.34);".encode(), environment=environment)
            primary, copy_key, wrong = root / 'primary.key', root / 'recovered.key', root / 'wrong.key'
            common.run(['age-keygen', '-o', primary]); primary.chmod(0o600)
            recipient = common.run(['age-keygen', '-y', primary]).decode().strip()
            shutil.copyfile(primary, copy_key); copy_key.chmod(0o600)
            common.run(['age-keygen', '-o', wrong]); wrong.chmod(0o600)
            with plaintext_directory() as directory:
                began = time.monotonic()
                dump = directory / 'database.dump'
                def concurrent_write():
                    common.run(psql, payload="UPDATE s10_recovery_case SET amount=777.77 WHERE id=1; INSERT INTO s10_recovery_case VALUES (2,'Μετά το στιγμιότυπο',99.99);".encode(), environment=environment)
                manifest = pg.dump(psql, pg_dump, dump, environment, during_snapshot=concurrent_write)
                manifest.update(format='accounting-s10-v1')
                encrypted = root / 'synthetic.tar.age'
                recovery = {'secret_versions': {'django': 1, 'postgres': 1}, 'identity_payloads': 'excluded'}
                encrypt(dump, manifest, recovery, recipient, encrypted)
                primary.unlink()  # Key recovery must not depend on the original.
                fresh = directory / 'decoded'; fresh.mkdir(mode=0o700)
                restored_manifest, restored_config = decrypt(encrypted, copy_key, fresh)
                require(restored_config == recovery, 'Recovery references differ')
                common.run([args.native_bin / 'createdb', 's10_recovered'], environment=environment)
                pg.restore_dump([args.native_bin / 'pg_restore', '--dbname=s10_recovered'], fresh / 'database.dump', environment)
                target = [args.native_bin / 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '--dbname=s10_recovered']
                verified = pg.verify_tables(target, restored_manifest['tables'], environment)
                row = common.run(target, payload=b'SELECT amount FROM s10_recovery_case WHERE id=1; SELECT count(*) FROM s10_recovery_case;\n', environment=environment).decode().strip()
                require(row == '12.34\n1', 'Dump did not use the exported snapshot')
                rejected = {}
                for label, ciphertext, key in (('wrong_key', encrypted, wrong), ('tampered_ciphertext', root / 'tampered.age', copy_key)):
                    if label == 'tampered_ciphertext':
                        data = bytearray(encrypted.read_bytes()); data[-20] ^= 1; ciphertext.write_bytes(data)
                    bad = directory / label; bad.mkdir(mode=0o700)
                    try:
                        decrypt(ciphertext, key, bad)
                    except common.CommandFailure:
                        rejected[label] = True
                    else:
                        raise RuntimeError('Invalid encrypted backup was accepted')
                common.run(target, payload=b'DELETE FROM s10_recovery_case;\n', environment=environment)
                try:
                    pg.verify_tables(target, restored_manifest['tables'], environment)
                except ValueError:
                    rejected['changed_restored_rows'] = True
                else:
                    raise RuntimeError('Changed recovered rows were accepted')
                # Bound failure also rolls back/releases the source snapshot.
                try:
                    pg.dump(psql, pg_dump, directory / 'limited.dump', environment, max_bytes=64)
                except ValueError:
                    rejected['oversized_dump'] = True
                else:
                    raise RuntimeError('Dump size limit was ignored')
                active = common.run(psql, payload=b"SELECT count(*) FROM pg_stat_activity WHERE state='idle in transaction';\n", environment=environment).decode().strip()
                require(active == '0', 'A backup snapshot transaction leaked')
                elapsed = round(time.monotonic() - began, 3)
            require(not directory.exists(), 'Native recovery plaintext was retained')
    return {'step': 'S10', 'status': 'Prepared', 'mode': 'native-postgresql17-age', 'verified_at': common.now(),
            'postgresql': pg_version, 'age': version, 'restore_seconds_including_negative_tests': elapsed, **verified,
            'concurrent_source_write_excluded': True, 'separate_key_copy_with_primary_removed': True,
            'greek_text_and_exact_decimal_recovered': True, 'denied_cases': rejected,
            'plaintext_and_test_clusters_removed': True, 'gcs_execution': False, 'docker_execution': False,
            'snapshot_transactions_released': True,
            'public_monitoring_or_alert_delivery': False, 'accepted_dataset_rpo_rto': 'Pending'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-bin', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--age-bin', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = verify(args)
    if args.report:
        preview.private_json(args.report, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

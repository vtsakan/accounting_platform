#!/usr/bin/env python3
"""S25 private dry-run report and optional, isolated PG15 -> PG17 rehearsal."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

from dev import ROOT, require_local_docker
from legacy_plan import build_plan, digest, read_json, require
from legacy_restore import (archive_versions, archive_version_numbers, client_major, client_version_number,
    diagnostic_parameters, failure_category, redact, safe_error_lines, validate_rehearsal_pair, validate_server)

DOCS = ROOT / 'docs/implementation'
FIXTURES = DOCS / 'fixtures'
IMAGE_POLICY_PATH = FIXTURES / 's25-image-pins.json'
IMAGE_POLICY = read_json(IMAGE_POLICY_PATH)
PG17 = IMAGE_POLICY['postgres17']['reference']
PG15_DISCOVERY = IMAGE_POLICY['postgres15']['reference']  # Historical name; now an immutable pin.
CONTEXT = 'sha256:aa53c8f70d8ca11881457a7c80ee7e21684c8b4212a86fe9dbfe28ed95220ba0'
APPLICATION_REVISION = 'a170a885ca186b194f4df557fad2ced6f59fa034'
APP_REGISTRY = 'europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:08cf99dc5ab117b08db3739600e4f6486611a6c63238cb4a2b9efba141b115b1'
APP_LOCAL = 'sha256:c10aada2826f7110ba43870e0a069d01037f5bd72ed1d3cc1bd00072778d02f6'
S25_FILES = ('legacy_plan.py', 'legacy_settings.py', 'legacy_worker.py')
LABEL = 'gr.accounting.s25.run'
MAX_DUMP = 256 * 1024 * 1024
DISPOSITIONS = {'import':'Εισαγωγή','archive':'Αρχείο','quarantine':'Εξαίρεση για έλεγχο',
    'hold-unallocated':'Κίνηση χωρίς αντιστοίχιση','opening-component':'Περιλαμβάνεται στο αρχικό υπόλοιπο'}
FIELDS_EL = {'opening':'Αρχικό υπόλοιπο','balance':'Τελικό υπόλοιπο','income':'Λειτουργικές εισπράξεις',
    'expense':'Λειτουργικές πληρωμές','transfer_in':'Εισερχόμενες μεταφορές','transfer_out':'Εξερχόμενες μεταφορές',
    'amount':'Ποσό','allocated':'Αντιστοιχισμένο ποσό','outstanding':'Ανεξόφλητο υπόλοιπο','unallocated':'Αδιάθετο ποσό',
    'transfer':'Εσωτερική μεταφορά','allocation-source':'Πηγή αντιστοίχισης','allocation-charge':'Χρέωση αντιστοίχισης',
    'allocation-amount':'Ποσό αντιστοίχισης','allocation-date':'Ημερομηνία αντιστοίχισης','source-coverage':'Κάλυψη πηγής',
    'row-count':'Πλήθος εγγραφών','actor-required':'Απουσία υπευθύνου','events-recorded':'Καταγραφή ιστορικού',
    'retained-source-digest':'Αποτύπωμα πηγής','source-exclusions':'Ανεξήγητη διαφορά πηγής',
    'agreement':'Συμφωνία','party':'Συναλλασσόμενος','direction':'Κατεύθυνση','effective-date':'Ημερομηνία ισχύος',
    'due-date':'Ημερομηνία λήξης','cash-account':'Ταμείο','audit-actor':'Επώνυμη καταχώριση ιστορικού',
    'paired-transfer':'Ζεύγος εσωτερικής μεταφοράς'}
ISSUES_EL = {'unmapped-office':'Γραφείο χωρίς αντιστοίχιση','missing-review-reference':'Λείπει αναφορά ανασκόπησης',
    'unmapped-user':'Χρήστης χωρίς ενεργή χαρτογράφηση','invalid-reference':'Μη έγκυρη σύνδεση',
    'foreign-or-missing-reference':'Ξένη ή ανύπαρκτη εγγραφή','invalid-settlement-link':'Μη έγκυρη σύνδεση εξόφλησης',
    'invalid-fields-or-unreviewed-terms':'Μη έγκυρα πεδία ή ανεξέλεγκτοι όροι','duplicate-identity':'Διπλή ταυτότητα',
    'category-cycle':'Κυκλική κατηγορία','ambiguous-transfer':'Μη τεκμηριωμένη μεταφορά',
    'blocked-master':'Εξάρτηση από μη αποδεκτή εγγραφή'}


def sha(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024),b''):
            checksum.update(block)
    return 'sha256:' + checksum.hexdigest()


def private_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        require(path.is_file() and not path.is_symlink(), 'Μη ασφαλές αρχείο αναφοράς.')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')


def output_path(path):
    path = Path(path).expanduser().resolve()
    require(path.is_relative_to((ROOT / 'private').resolve()) or not path.is_relative_to(ROOT.resolve()),
        'Οι αναφορές πηγής αποθηκεύονται στο private/ ή έξω από το Git.')
    return path


def safe_cell(value):
    text = str(value)
    return "'" + text if text[:1] in {'=', '+', '-', '@', '\t', '\r'} else text


def csv_report(path, headings, rows):
    buffer = io.StringIO(); writer = csv.writer(buffer, delimiter=';')
    writer.writerow(headings)
    for row in rows:
        writer.writerow([safe_cell(value) for value in row])
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8-sig', newline='') as stream:
        stream.write(buffer.getvalue())


def analyse(source, review, report):
    plan = build_plan(source, review); report = output_path(report)
    private_json(report, plan)
    csv_report(report.with_suffix('.csv'), ['Εγγραφή πηγής','Γραφείο','Αντιμετώπιση','Εξαιρέσεις','Αιτιολόγηση','Αναφορά ανασκόπησης'],
        ([e['key'], e['office'] or '', DISPOSITIONS[e['action']], ', '.join(ISSUES_EL.get(v,v) for v in e['issues']), e['disposition_reason'], e['review_reference']] for e in plan['entries']))
    csv_report(report.parent/(report.stem+'-source-balances.csv'),
        ['Ταμείο πηγής','Παλαιό υπόλοιπο','Αποδεκτό υπόλοιπο','Εξαιρούμενο καθαρό ποσό','Ανεξήγητη διαφορά','Μη αποτιμημένες εγγραφές'],
        ([key,row['raw_balance'],row['accepted_balance'],row['excluded_signed_cash'],row['unexplained_difference'],', '.join(row['unpriced_source_rows'])]
            for key,row in plan['raw_account_reconciliation'].items()))
    return plan


class Runner:
    def __init__(self, work):
        self.nonce = secrets.token_hex(10); self.prefix = 'accounting-s25-' + self.nonce
        self.work = Path(work); self.events = []; self.resources = []; self.stage = 'initialise'
        self.environment = {k: v for k,v in os.environ.items() if not k.startswith(('DB_', 'DJANGO_', 'PG', 'COMPOSE_', 'AUTH_', 'S25_'))}
        self.values = {'S25_NONCE':self.nonce, 'S25_SYNTHETIC':'1', 'S25_SIGNING_KEY':secrets.token_urlsafe(64),
            'S25_OWNER_PASSWORD':secrets.token_urlsafe(36), 'DB_PASSWORD':secrets.token_urlsafe(36)}
        self.admin_password = secrets.token_urlsafe(36)
        self.report_dir = ROOT / 'private/s25' / self.nonce
        self.failure_summary = None
        self.restore_context = None
        self.postgres_versions = None
        self.failure_lock = threading.Lock()

    def save_failure(self, operation, code, stderr):
        with self.failure_lock:
            return self._save_failure(operation,code,stderr)

    def _save_failure(self, operation, code, stderr):
        # Keep the first failure; cleanup errors must not erase its evidence.
        if self.failure_summary is not None:
            return self.failure_summary
        text = stderr.decode(errors='replace') if isinstance(stderr, bytes) else str(stderr)
        secrets_to_hide = [self.admin_password, *[v for k,v in self.values.items() if k.endswith(('_PASSWORD','_KEY'))]]
        summary = {'step':'S25','status':'Failed','stage':self.stage,'operation':operation,
            'exit_code':code,'category':failure_category(text),'error_headers':safe_error_lines(text,secrets_to_hide),
            'restore_metadata':self.restore_context,'postgres_versions':self.postgres_versions,
            'unrecognized_parameters':diagnostic_parameters(text,secrets_to_hide),'root_cause_confirmed':False}
        try:
            private_json(self.report_dir/'failure-private.json', {**summary, 'stderr_redacted':redact(text,secrets_to_hide)[-32768:]})
            private_json(self.report_dir/'failure-summary.json',summary)
            self.failure_summary = self.report_dir/'failure-summary.json'
        except OSError:
            summary['diagnostic_file_written'] = False
            self.failure_summary = 'S25-DIAG console output; diagnostic file unavailable'
        print('S25-DIAG '+json.dumps(summary,ensure_ascii=False,sort_keys=True),file=sys.stderr,flush=True)
        return self.failure_summary

    def run(self, command, *, data=None, file=None, allowed=(0,), timeout=300):
        # Never attach to caller stdin; operator scripts are often pasted as heredocs.
        environment = dict(self.environment)
        try:
            with (Path(file).open('wb') if file else tempfile.TemporaryFile()) as stdout:
                result = subprocess.run([str(c) for c in command], input=data, stdin=subprocess.DEVNULL if data is None else None,
                    stdout=stdout, stderr=subprocess.PIPE, env=environment, timeout=timeout, check=False)
                if file:
                    require(Path(file).stat().st_size <= MAX_DUMP, 'Το στιγμιότυπο υπερβαίνει το όριο δοκιμής.')
                    output = b''
                else:
                    require(stdout.tell() <= 64 * 1024 * 1024, 'Η έξοδος υπερβαίνει το όριο δοκιμής.')
                    stdout.seek(0); output = stdout.read()
        except subprocess.TimeoutExpired:
            self.save_failure(Path(str(command[0])).name,None,'Command timeout')
            raise RuntimeError('Έληξε ο χρόνος της λειτουργίας ' + self.stage) from None
        if result.returncode not in allowed:
            details = self.save_failure('pg_restore' if 'pg_restore' in command else Path(str(command[0])).name,
                result.returncode,result.stderr)
            diagnostic = next((line for line in result.stderr.decode(errors='replace').splitlines() if line.startswith('S25-WORKER ')), '')
            raise RuntimeError(f'{self.stage}: {Path(str(command[0])).name} exit {result.returncode}; diagnostic: {details}' + ('; ' + diagnostic if diagnostic else ''))
        return output, result.returncode, result.stderr

    def docker(self, *args, **kwargs):
        return self.run(['docker', *args], **kwargs)

    def inspect_image(self, image):
        return json.loads(self.docker('image','inspect',image)[0])[0]

    def pinned(self, image):
        _, code, _ = self.docker('image','inspect',image, allowed=(0,1))
        if code:
            self.docker('pull','--platform','linux/amd64',image, timeout=600)
        info = self.inspect_image(image)
        require(info['Architecture'] == 'amd64' and info['Os'] == 'linux', 'Απαιτείται εικόνα Linux amd64.')
        digests = info.get('RepoDigests', [])
        if '@sha256:' in image:
            required_digest = image.split('@',1)[1]
            require(any(value.split('@',1)[-1] == required_digest and value.split('@',1)[0] in {
                'postgres','docker.io/library/postgres','index.docker.io/library/postgres'} for value in digests),
                'Η αμετάβλητη αναφορά εικόνας δεν συμφωνεί.')
            return image
        require(digests, 'Δεν βρέθηκε αμετάβλητο digest εικόνας.')
        return digests[0]

    def own(self, kind, name):
        output = self.docker(kind,'inspect',name)[0]
        record = json.loads(output)[0]
        labels = record.get('Config', {}).get('Labels') if kind == 'container' else record.get('Labels')
        require((labels or {}).get(LABEL) == self.nonce, 'Ο πόρος δεν ανήκει στη συγκεκριμένη δοκιμή.')
        return record

    def psql(self, container, database, query, *, user='postgres'):
        self.own('container',container)
        return self.docker('exec','--interactive',container,'psql','-X','-qAt','-v','ON_ERROR_STOP=1',
            '-U',user,'-d',database, data=query.encode())[0].decode()

    def worker(self, action, source, review):
        kind = 'source' if action in {'seed','export-source'} else 'raw' if action == 'export-raw' else 'target'
        host = self.pg15 if kind == 'source' else self.pg17
        values = {**self.values, 'DB_NAME':'s25_' + kind + '_' + self.nonce,
            'DB_HOST':host, 'DB_PORT':'5432', 'DB_USER':'postgres' if kind != 'target' else 's25_runner',
            'DB_PASSWORD':self.admin_password if kind != 'target' else self.values['DB_PASSWORD']}
        worker_name = self.prefix + '-worker-' + secrets.token_hex(5)
        env_file = self.work / (worker_name + '.env')
        env_file.write_text(''.join(k+'='+v+'\n' for k,v in values.items())); env_file.chmod(0o600)
        command = ['run','--rm','--name',worker_name,'--interactive','--platform','linux/amd64','--network',self.network,
            '--label',LABEL+'='+self.nonce,'--env-file',env_file,'--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,noexec,nosuid,size=128m',
            '--mount','type=bind,src='+str(ROOT / 'tools')+',dst=/opt/s25,readonly',
            '--entrypoint','python',self.application,'/opt/s25/legacy_worker.py',action]
        try:
            output, code, stderr = self.docker(*command, data=json.dumps({'source':source,'review':review}).encode(), allowed=(0,42), timeout=600)
        finally:
            # A timed-out Docker client can leave its container behind.
            _, exists_code, _ = self.docker('container','inspect',worker_name,allowed=(0,1))
            if exists_code == 0:
                try:
                    self.own('container',worker_name); self.docker('rm','--force',worker_name)
                except Exception:
                    self.resources.append(('container',worker_name))
            env_file.unlink(missing_ok=True)
        if action == 'inject-failure':
            require(code == 42 and b'S25-INJECTED-ROLLBACK' in stderr, 'Δεν αποδείχθηκε ο σκόπιμος αντιλογισμός παρτίδας.')
            return {'atomic_failure_injected':True}
        require(code == 0, 'Μη αναμενόμενη διακοπή εισαγωγής.')
        lines = [line for line in output.decode().splitlines() if line.startswith('S25-RESULT ')]
        require(len(lines) == 1, 'Λείπει το μοναδικό αποτέλεσμα δοκιμής.')
        return json.loads(lines[0][11:])

    def fingerprints(self, container, database):
        # Include the source/ID ledger as well as every application/auth table.
        from operations_pg import FINGERPRINT_SQL, fingerprints
        sql = FINGERPRINT_SQL.replace("schemaname='public'", "schemaname IN ('public','s25_control','s25_import')")
        return fingerprints(self.psql(container,database,sql))

    def dump(self, tool_container, host, database, path):
        self.docker('exec','--env','PGPASSWORD='+self.admin_password,tool_container,
            'pg_dump','--host',host,'--username','postgres','--dbname',database,
            '--format','custom','--quote-all-identifiers','--no-owner','--no-privileges',file=path, timeout=300)

    def restore(self, container, database, path, *, user='postgres'):
        phase = self.stage
        self.own('container',container)
        major = 15 if container == self.pg15 else 17
        allowed = ({'s25_source_restore_'+self.nonce} if container == self.pg15 else
            {'s25_raw_'+self.nonce,'s25_target_'+self.nonce} if container == self.pg17 else set())
        require(database in allowed and user == ('s25_runner' if database == 's25_target_'+self.nonce else 'postgres'),
            'Μη επιτρεπόμενος στόχος ή ρόλος ανάκτησης S25.')
        path = Path(path)
        require(not path.is_symlink() and path.resolve(strict=True).is_relative_to(self.work.resolve())
            and 5 < path.stat().st_size <= MAX_DUMP,'Μη έγκυρο ιδιωτικό στιγμιότυπο S25.')
        with path.open('rb') as stream:
            require(stream.read(5) == b'PGDMP','Το στιγμιότυπο δεν είναι αρχείο PostgreSQL custom format.')
        self.stage = phase+'/target-preflight'
        info = json.loads(self.psql(container,database,"""SELECT json_build_object(
            'database',current_database(),'user',current_user,
            'version',current_setting('server_version_num')::integer,
            'port',current_setting('port')::integer,
            'read_only',current_setting('transaction_read_only'),
            'user_tables',(SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')))::text;""",user=user))
        self.restore_context = {'server_major':info.get('version',0)//10000,'expected_major':major,
            'server_version_num':info.get('version'),
            'role_matches':info.get('user')==user,'database_matches':info.get('database')==database,
            'read_only':info.get('read_only'),'user_tables':info.get('user_tables')}
        validate_server(info,database=database,user=user,major=major)
        version = self.docker('exec','--user','0:0',container,'pg_restore','--version')[0].decode()
        require(client_major(version) == major,'Το pg_restore δεν συμφωνεί με τη δοκιμαστική έκδοση στόχου.')
        self.restore_context['pg_restore_version_num'] = client_version_number(version)
        remote = '/s25-recovery/restore-'+secrets.token_hex(8)+'.dump'
        try:
            self.stage = phase+'/archive-copy'
            # docker cp cannot reliably access user-mounted tmpfs paths.
            # Run the writer in the container mount namespace; pg_restore still
            # receives a seekable regular file, never this stdin stream.
            self.restore_context['archive_bytes_match'] = False
            self.docker('exec','--interactive','--user','0:0',container,'sh','-c',
                'set -C; umask 077; exec cat > "$1"','s25-archive-copy',remote,data=path.read_bytes())
            self.docker('exec','--user','0:0',container,'chmod','0600',remote)
            self.stage = phase+'/archive-copy-verify'
            checksum = self.docker('exec','--user','0:0',container,'sha256sum',remote)[0].decode().split()
            require(bool(checksum) and checksum[0] == sha(path).removeprefix('sha256:'),
                'Το αρχείο μέσα στο tmpfs διαφέρει από το αρχικό στιγμιότυπο· η ανάκτηση σταμάτησε πριν από SQL.')
            self.restore_context['archive_bytes_match'] = True
            self.stage = phase+'/archive-preflight'
            toc = self.docker('exec','--user','0:0',container,'pg_restore','--list',remote)[0].decode()
            metadata = archive_versions(toc); self.restore_context.update(metadata)
            self.restore_context.update(archive_version_numbers(toc))
            require(metadata['dumped_by_major'] == major and metadata['source_major'] <= major,
                'Η έκδοση αρχείου δεν συμφωνεί με την αναμενόμενη πηγή/στόχο· δεν γίνεται παράκαμψη SQL.')
            self.stage = phase+'/restore-execute'
            password = self.values['DB_PASSWORD'] if user == 's25_runner' else self.admin_password
            self.docker('exec','--user','0:0','--env','PGPASSWORD='+password,container,'pg_restore',
                '--host','127.0.0.1','--port','5432','--username',user,'--dbname',database,
                '--single-transaction','--exit-on-error','--no-owner','--no-privileges',remote)
        finally:
            _, cleanup_code, _ = self.docker('exec','--user','0:0',container,'rm','-f','--',remote,allowed=(0,1,125,126,127))
            if cleanup_code:
                private_json(self.report_dir/'restore-file-cleanup.json',{'container':container,'failed':True})
        self.stage = phase

    def start(self, application, source_image=PG15_DISCOVERY):
        self.stage = 'image-identity'
        _, code, _ = self.docker('image','inspect',application,allowed=(0,1))
        if code:
            require(application == APP_REGISTRY, 'Η τοπική ελεγμένη εικόνα λείπει· χρησιμοποιήστε --image με το αμετάβλητο registry digest του S24A.')
            self.docker('pull','--platform','linux/amd64',application,timeout=600)
        info = self.inspect_image(application)
        require(info['Architecture'] == 'amd64' and info['Os'] == 'linux' and info['Config']['User'] == '10001:10001', 'Μη αναμενόμενη ταυτότητα εφαρμογής.')
        labels = info['Config'].get('Labels', {})
        require(labels.get('org.opencontainers.image.revision') == APPLICATION_REVISION
            and labels.get('gr.accounting.source-context') == CONTEXT, 'Χρησιμοποιήστε την ήδη ελεγμένη εικόνα S24A.')
        self.application = info['Id']
        self.stage = 'postgres-image-resolution'
        # The S25 source and target are pinned as one reviewed maintenance pair.
        # Production/VM pins remain in their existing independent files.
        require(source_image == PG15_DISCOVERY or re.fullmatch(r'(?:postgres|docker.io/library/postgres)@sha256:[a-f0-9]{64}',source_image),
            'Η πηγή χρειάζεται επίσημη εικόνα PostgreSQL με αμετάβλητο digest.')
        self.image15 = self.pinned(source_image); self.image17 = self.pinned(PG17)
        self.network = self.prefix + '-net'; self.volume = self.prefix + '-pg17'
        self.pg15 = self.prefix + '-pg15'; self.pg17 = self.prefix + '-pg17'
        self.docker('network','create','--internal','--label',LABEL+'='+self.nonce,self.network)
        self.resources.append(('network',self.network))
        self.docker('volume','create','--label',LABEL+'='+self.nonce,self.volume)
        self.resources.append(('volume',self.volume))
        admin_env = self.work / 'postgres.env'
        admin_env.write_text('POSTGRES_PASSWORD='+self.admin_password+'\n'); admin_env.chmod(0o600)
        for name, image, mount in [(self.pg15,self.image15,['--tmpfs','/var/lib/postgresql/data:rw,nosuid,size=512m']),
                (self.pg17,self.image17,['--mount','type=volume,src='+self.volume+',dst=/var/lib/postgresql/data'])]:
            self.stage = 'database-start'
            self.docker('run','--detach','--name',name,'--platform','linux/amd64','--network',self.network,
                '--label',LABEL+'='+self.nonce,'--env-file',admin_env,
                '--tmpfs','/s25-recovery:rw,noexec,nosuid,size=256m,mode=0700',*mount,image)
            self.resources.append(('container',name))
            deadline = time.monotonic() + 120
            while True:
                _, code, _ = self.docker('exec',name,'pg_isready','-U','postgres',allowed=(0,1,2))
                if code == 0:
                    break
                require(time.monotonic() < deadline, 'Η απομονωμένη βάση δεν είναι έτοιμη.'); time.sleep(1)
            record = self.own('container',name)
            require(not record['HostConfig'].get('PortBindings'), 'Δεν επιτρέπονται δημοσιευμένες θύρες δοκιμής.')
        self.stage = 'postgres-maintenance-pair'
        self.postgres_versions = {}
        for prefix,container in [('source',self.pg15),('target',self.pg17)]:
            self.postgres_versions[prefix+'_server'] = int(self.psql(container,'postgres',"SELECT current_setting('server_version_num');").strip())
            for command in ('pg_dump','pg_restore'):
                version = self.docker('exec',container,command,'--version')[0].decode()
                self.postgres_versions[prefix+'_'+command] = client_version_number(version)
        validate_rehearsal_pair(self.postgres_versions)
        print('[S25] Ζεύγος PostgreSQL 15.20 → 17.12 και εργαλεία επιβεβαιώθηκαν.',flush=True)
        source_db = 's25_source_' + self.nonce; raw_db = 's25_raw_' + self.nonce; target_db = 's25_target_' + self.nonce
        # All identifiers and passwords below are generated ASCII, never external input.
        self.psql(self.pg15,'postgres',f'CREATE DATABASE {source_db} TEMPLATE template0;')
        self.psql(self.pg17,'postgres',f"CREATE ROLE s25_runner LOGIN PASSWORD '{self.values['DB_PASSWORD']}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;\nCREATE DATABASE {raw_db} TEMPLATE template0;\nCREATE DATABASE {target_db} OWNER s25_runner TEMPLATE template0;")
        return source_db, raw_db, target_db

    def reset_target(self, database, baseline):
        require(database == 's25_target_' + self.nonce, 'Μη επιτρεπόμενος στόχος επαναφοράς.')
        self.own('volume',self.volume)
        marker = self.psql(self.pg17,database,'SELECT nonce FROM s25_control.identity;').strip()
        require(marker == self.nonce, 'Ο στόχος επαναφοράς δεν ανήκει στη δοκιμή.')
        self.psql(self.pg17,'postgres',f'DROP DATABASE {database} WITH (FORCE);\nCREATE DATABASE {database} OWNER s25_runner TEMPLATE template0;')
        self.restore(self.pg17,database,baseline,user='s25_runner')

    def cleanup(self):
        failures = []
        for kind,name in reversed(self.resources):
            try:
                self.own(kind,name)
                if kind == 'container':
                    self.docker('rm','--force',name)
                else:
                    self.docker(kind,'rm',name)
            except Exception:
                failures.append({'kind':kind,'name':name})
        return failures


def archive(runner, source, review, baseline, paths, identity):
    from operations_common import check_age, identity_file, recipient_id
    check_age(); identity = identity_file(identity)
    recipient = runner.run(['age-keygen','-y',identity])[0].decode().strip()
    require(re.fullmatch(r'age1[a-z0-9]{58}',recipient), 'Μη έγκυρος παραλήπτης age.')
    config_path = ROOT / 'private/operations.json'
    if config_path.is_file():
        config = read_json(config_path)
        require(config['recipient'] == recipient and config['recipient_id'] == recipient_id(recipient), 'Το κλειδί δεν συμφωνεί με τον υπάρχοντα παραλήπτη αντιγράφων.')
    destination = Path.home() / '.config/totalaccounting/legacy-rehearsals' / runner.nonce
    destination.mkdir(parents=True,exist_ok=False,mode=0o700)
    archive_path = runner.work / 'rehearsal.tar'
    values_path = runner.work / 'isolated-environment.json'
    private_json(values_path,runner.values)
    source_path = runner.work / 'source.json'; review_path = runner.work / 'review.json'
    private_json(source_path,source); private_json(review_path,review)
    manifest = {'schema':1,'nonce':runner.nonce,'source_sha256':digest(source),'review_sha256':digest(review),
        'files':{p.name:sha(p) for p in [*paths,baseline,values_path,source_path,review_path]},
        'postgres15_image':runner.image15,'postgres17_image':runner.image17,'application_image':runner.application,
        'postgres_versions':runner.postgres_versions,'image_policy_sha256':sha(IMAGE_POLICY_PATH),
        'signing_and_mfa_key_material_included':True,'age_private_identity_included':False}
    manifest_path = runner.work / 'manifest.json'; private_json(manifest_path,manifest)
    with tarfile.open(archive_path,'w',format=tarfile.PAX_FORMAT) as stream:
        for path in [*paths,baseline,values_path,source_path,review_path,manifest_path]:
            stream.add(path,arcname=path.name,recursive=False)
    encrypted = destination / 'rehearsal.tar.age'
    runner.run(['age','--recipient',recipient,'--output',encrypted,archive_path]); encrypted.chmod(0o600)
    decrypted = runner.work / 'checked-rehearsal.tar'
    runner.run(['age','--decrypt','--identity',identity,'--output',decrypted,encrypted])
    require(sha(archive_path) == sha(decrypted), 'Το αντίγραφο δεν αποκρυπτογραφήθηκε ακριβώς.')
    # Restore from bytes read from the encrypted archive, not from the original dump.
    restored = runner.work / 'recovered'; restored.mkdir(mode=0o700)
    with tarfile.open(decrypted,'r:') as stream:
        members = stream.getmembers()
        require(len(members) == len(manifest['files'])+1 and all(m.isfile() and '/' not in m.name and m.size <= MAX_DUMP for m in members), 'Μη ασφαλές αρχείο ανάκτησης.')
        for member in members:
            data = stream.extractfile(member).read()
            path = restored / member.name; path.write_bytes(data); path.chmod(0o600)
        for name, checksum in manifest['files'].items():
            require(sha(restored/name) == checksum, 'Αλλοιωμένο μέλος αντιγράφου.')
    recovered_values = read_json(restored/'isolated-environment.json')
    require(recovered_values == runner.values, 'Δεν ανακτήθηκε το υλικό κρυπτογράφησης MFA.')
    runner.values = recovered_values
    return {'path':str(encrypted),'sha256':sha(encrypted),'decryption_checked':True,
        'source_native15_and_forward17_dumps':True,'target_starting_snapshot':True,
        'required_synthetic_signing_and_mfa_keys_included':True}, restored


def rehearse(args):
    from operations_common import require_tmpfs, check_age, identity_file
    # Executed only by the operator; new planner tests never invoke Docker/cloud.
    unit = subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tools'),'-p','test_s25.py'],
        cwd=ROOT,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=120)
    require(unit.returncode == 0, 'Απέτυχαν οι έλεγχοι σχεδιασμού S25. Εκτελέστε: python3 -m unittest discover -s tools -p test_s25.py -v')
    counts = re.findall(r'Ran ([0-9]+) tests?',unit.stderr)
    require(len(counts) == 1 and int(counts[0]) > 0 and 'skipped=' not in unit.stderr, 'Μη πλήρης εκτέλεση ελέγχων σχεδιασμού.')
    tool_manifest = {name:sha(ROOT/'tools'/name) for name in (*S25_FILES,'legacy_migration.py','legacy_restore.py','verify_s25.py','test_s25.py')}
    image_policy_sha256 = sha(IMAGE_POLICY_PATH)
    require_local_docker(); check_age(); identity_file(args.identity)
    require_tmpfs('/dev/shm')
    source = read_json(FIXTURES/'s25-source.json'); review = read_json(FIXTURES/'s25-review.json')
    require(review['mode'] == 'synthetic' and source['lineage'] == 'synthetic-s25-v1', 'Η πλήρης εκτέλεση δέχεται μόνο το συνθετικό παράδειγμα S25.')
    plan = build_plan(source,review)
    require(not plan['unresolved'], 'Το συνθετικό παράδειγμα έχει εκκρεμείς εξαιρέσεις.')
    # This entry point deliberately accepts no live DB URL, Docker project or VM target.
    with tempfile.TemporaryDirectory(prefix='accounting-s25-',dir='/dev/shm') as work:
        runner = Runner(work); report_dir = ROOT / 'private/s25' / runner.nonce
        report_dir.mkdir(parents=True,mode=0o700); proof = None; failures = []
        try:
            print('[S25] Απομονωμένη συνθετική δοκιμή: ' + runner.prefix, flush=True)
            source_db, raw_db, target_db = runner.start(args.image,args.source_image)
            runner.stage = 'legacy-pg15-seed'; runner.worker('seed',source,review)
            runner.stage = 'legacy-read-only-snapshot'
            runner.psql(runner.pg15,'postgres',f'ALTER DATABASE {source_db} SET default_transaction_read_only=on;')
            actual_source = runner.worker('export-source',source,review)
            require(digest(actual_source) == digest(source), 'Η πραγματική PG15 πηγή δεν συμφωνεί με το ελεγμένο παράδειγμα.')
            source_fingerprint = runner.fingerprints(runner.pg15,source_db)
            native = Path(work)/'source-native15.dump'; forward = Path(work)/'source-forward17.dump'
            runner.dump(runner.pg15,runner.pg15,source_db,native)
            runner.dump(runner.pg17,runner.pg15,source_db,forward)
            runner.stage = 'logical-15-to-17'
            print('[S25] Έλεγχος αρχείου και επαναφορά στον νέο στόχο PostgreSQL 17.',flush=True)
            runner.restore(runner.pg17,raw_db,forward)
            require(source_fingerprint == runner.fingerprints(runner.pg17,raw_db), 'Το λογικό αντίγραφο 15→17 διαφέρει.')
            require(digest(runner.worker('export-raw',source,review)) == digest(source), 'Η κανονική εξαγωγή 17 διαφέρει.')
            runner.stage = 'target-current-schema'; runner.worker('init',source,review)
            role = runner.psql(runner.pg17,target_db,"SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication FROM pg_roles WHERE rolname=current_user;",user='s25_runner').strip()
            require(role == 'f', 'Η εφαρμογή δεν χρησιμοποιεί περιορισμένο ρόλο.')
            baseline_fingerprint = runner.fingerprints(runner.pg17,target_db)
            baseline = Path(work)/'target-start.dump'; runner.dump(runner.pg17,runner.pg17,target_db,baseline)
            runner.stage = 'encrypted-recovery-point'
            backup, restored = archive(runner,source,review,baseline,[native,forward],args.identity)
            plan_path = report_dir/'dry-run.json'; analyse(source,review,plan_path)
            require(baseline_fingerprint == runner.fingerprints(runner.pg17,target_db), 'Η ανάλυση άλλαξε τη βάση.')
            runner.stage = 'atomic-import-rollback'; runner.worker('inject-failure',source,review)
            require(baseline_fingerprint == runner.fingerprints(runner.pg17,target_db), 'Η αποτυχημένη παρτίδα άφησε εγγραφές.')
            runner.stage = 'concurrent-idempotent-import'
            with ThreadPoolExecutor(max_workers=2) as pool:
                tasks = [pool.submit(runner.worker,'apply',source,review) for _ in range(2)]
                results = [task.result() for task in tasks]
            require(sorted(r['replayed'] for r in results) == [False,True] and results[0]['mapping'] == results[1]['mapping'], 'Η ταυτόχρονη εισαγωγή δεν είναι ακριβώς επαναλήψιμη.')
            after = runner.fingerprints(runner.pg17,target_db)
            require(runner.worker('apply',source,review)['replayed'], 'Η τρίτη εκτέλεση δεν αναγνώρισε την παρτίδα.')
            require(after == runner.fingerprints(runner.pg17,target_db), 'Η επανάληψη πρόσθεσε ή άλλαξε εγγραφές.')
            require(runner.worker('changed-replay',source,review)['changed_payload_denied'], 'Η αλλαγμένη πηγή δεν απορρίφθηκε.')
            require(after == runner.fingerprints(runner.pg17,target_db), 'Η αλλαγμένη επανάληψη άφησε εγγραφές.')
            runner.stage = 'append-only-source-ledger'
            for statement in ('UPDATE s25_import.record SET target=target;', 'DELETE FROM s25_import.record;', 'TRUNCATE s25_import.record;'):
                _,code,stderr = runner.docker('exec','--interactive',runner.pg17,'psql','-X','-qAt','-v','ON_ERROR_STOP=1',
                    '-U','s25_runner','-d',target_db,data=statement.encode(),allowed=(0,3))
                require(code == 3 and b'S25 source mapping is append only' in stderr, 'Το ιστορικό πηγής δεν είναι αμετάβλητο.')
            require(after == runner.fingerprints(runner.pg17,target_db), 'Ο έλεγχος ιστορικού άλλαξε εγγραφές.')
            runner.stage = 'financial-reconciliation'; reconciliation = runner.worker('reconcile',source,review)
            private_json(report_dir/'source-to-target.json',results[0]['mapping'])
            private_json(report_dir/'reconciliation.json',reconciliation)
            csv_report(report_dir/'reconciliation.csv', ['Εγγραφή πηγής','Έλεγχος','Αναμενόμενο','Πραγματικό','Συμφωνεί'],
                ([r['key'],FIELDS_EL[r['field']],r['expected'],r['actual'],'Ναι' if r['matched'] else 'Όχι'] for r in reconciliation['checks']))
            require(reconciliation['all_matched'], 'Βρέθηκαν διαφορές· δείτε την ιδιωτική αναφορά συμφωνίας.')
            runner.stage = 'source-native-restore-proof'
            restored_source = 's25_source_restore_' + runner.nonce
            runner.psql(runner.pg15,'postgres',f'CREATE DATABASE {restored_source} TEMPLATE template0;')
            runner.restore(runner.pg15,restored_source,restored/'source-native15.dump')
            require(source_fingerprint == runner.fingerprints(runner.pg15,restored_source), 'Η ανάκτηση της πηγής PG15 διαφέρει.')
            runner.stage = 'restore-rehearsal-starting-point'
            started = time.monotonic(); runner.reset_target(target_db,restored/'target-start.dump')
            require(baseline_fingerprint == runner.fingerprints(runner.pg17,target_db), 'Η αρχική κατάσταση δοκιμής δεν επανήλθε ακριβώς.')
            restore_seconds = round(time.monotonic()-started,3)
            runner.worker('apply',source,review)
            require(runner.worker('reconcile',source,review)['all_matched'], 'Η επανεισαγωγή μετά την ανάκτηση διαφέρει.')
            require(source_fingerprint == runner.fingerprints(runner.pg15,source_db), 'Η αρχική PG15 πηγή άλλαξε.')
            proof = {'step':'S25','status':'Verified','scope':'synthetic-isolated-migration-rehearsal',
                'verified_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'source_commit':'git:'+subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'source_sha256':digest(source),'review_sha256':digest(review),'plan_sha256':plan['plan_sha256'],
                'operator_tool_manifest':tool_manifest,'planner_tests_passed':int(counts[0]),
                'images':{'source_postgres15':runner.image15,'target_postgres17':runner.image17,'application':runner.application},
                'postgres_versions':runner.postgres_versions,'image_policy_sha256':image_policy_sha256,
                'preserved_application_context':CONTEXT,'production_suite_previously_passed':661,
                'production_suite_rerun':False,'docker_execution_by_operator':True,
                'secret_scan_this_step':'Not rerun; preserved S24A history evidence is not a new S25 scan',
                'logical_pg15_to_fresh_pg17':True,'source_original_unchanged':True,
                'restricted_role_migrations':True,'dry_run_no_business_writes':True,
                'all_source_identities_covered':plan['all_source_identities_covered'],'dispositions':plan['coverage'],
                'concurrent_single_batch_and_replay_without_duplicates':True,'atomic_failure_rollback':True,
                'changed_payload_denied_without_writes':True,'source_ledger_update_delete_truncate_denied':True,
                'reconciliation_checks':len(reconciliation['checks']),'all_financial_checks_matched':True,
                'encrypted_archive_and_required_synthetic_key_material':True,'recovery_identity_external_to_git':True,
                'source_pg15_native_restore_matched':True,'target_starting_point_restore_matched':True,
                'reimport_after_restore_matched':True,'synthetic_restore_seconds':restore_seconds,
                'local_demo_or_vm_changed':False,'human_accounts_or_mfa_changed':False,'real_client_data_imported':False,
                'd05_real_migration_review':'Pending','g2_release_acceptance':'Pending',
                'accepted_dataset_rpo_rto':'Pending','document_recovery':'Pending S38',
                'full_requirement_acceptance':'Pending','full_requirement_acceptances_pending':85,
                'source_tables_compared':len(source_fingerprint),'target_tables_compared':len(baseline_fingerprint)}
            private_json(report_dir/'backup-receipt.json',backup)
        except (Exception,KeyboardInterrupt) as error:
            if runner.failure_summary is None:
                runner.save_failure(type(error).__name__,None,str(error))
            raise
        finally:
            failures = runner.cleanup()
            private_json(report_dir/'resource-cleanup.json',{'leftover_owned_resources':failures})
            if failures:
                print('S25: Η εκκαθάριση χρειάζεται έλεγχο: '+str(report_dir/'resource-cleanup.json'),file=sys.stderr)
        require(not failures, 'Η τεχνική απόδειξη μένει εκκρεμής μέχρι την εκκαθάριση των δικών της πόρων.')
        require(tool_manifest == {name:sha(ROOT/'tools'/name) for name in tool_manifest}, 'Ο κώδικας εργαλείων άλλαξε κατά την εκτέλεση.')
        require(image_policy_sha256 == sha(IMAGE_POLICY_PATH),'Η πολιτική εικόνων άλλαξε κατά την εκτέλεση.')
        proof['owned_resources_removed'] = True
        private_json(report_dir/'verification.json',proof)
    # The tmpfs context has now removed all plaintext dumps, runtime secrets and recovered members.
    proof['plaintext_removed'] = True
    private_json(report_dir/'verification.json',proof)
    if args.record:
        record(proof)
    return {**proof,'private_reports':str(report_dir),'encrypted_recovery_archive':backup['path']}


def record(proof):
    # Only sanitized proof and the existing four implementation tracking files.
    import csv
    evidence = DOCS/'evidence/S25-verification.json'
    evidence.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    rows = list(csv.DictReader((DOCS/'steps.csv').open(newline=''))); fields = list(rows[0])
    for row in rows:
        if row['step_id'] == 'S25':
            row['status'] = 'Verified'; row['code_reference_commit'] = proof['source_commit'].removeprefix('git:')
            row['blocker'] = 'Synthetic technical gate passed; D05 real data, G2 and full acceptance Pending'
    with (DOCS/'steps.csv').open('w',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)
    state = DOCS/'state.md'; text = state.read_text()
    start, end = '<!-- S25-RESULT -->', '<!-- /S25-RESULT -->'
    require(start in text and end in text,'Λείπει το πεδίο κατάστασης S25.')
    text = text.split(start)[0]+start+'\nOperator S25 synthetic PostgreSQL 15→17 rehearsal Verified. Exact reconciliation, idempotent concurrency and encrypted source/target recovery passed. D05/G2/live migration and all 85 acceptances remain Pending.\n'+end+text.split(end)[1]
    lines = text.splitlines()
    lines[2] = 'Updated '+datetime.now(timezone.utc).date().isoformat()+'. Current step: **S25 Verified — synthetic technical rehearsal**. Next: **D05/G2 migration review; S26 when selected**.'
    text = '\n'.join(lines)+'\n'
    state.write_text(text)
    # Requirement acceptance stays Pending. Evidence appended without altering earlier receipts.
    path = DOCS/'traceability.csv'; rows = list(csv.DictReader(path.open(newline=''))); fields = list(rows[0])
    for row in rows:
        if row.get('requirement_id') in {'QR-03','QR-04','QR-09','QR-14'}:
            row['last_reviewed'] = proof['verified_at'][:10]
            note = ' S25 operator synthetic technical rehearsal passed; D05/G2/full acceptance remain Pending.'
            if note not in row['notes']:
                row['notes'] += note
            for column in ('evidence','evidence_paths'):
                if column in row and 'S25-verification.json' not in row[column]:
                    row[column] += '; docs/implementation/evidence/S25-verification.json'
    with path.open('w',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    dry = commands.add_parser('analyse',help='Μόνο ιδιωτική αναφορά, χωρίς βάση ή Docker')
    dry.add_argument('--source',type=Path,required=True);dry.add_argument('--review',type=Path,required=True)
    dry.add_argument('--report',type=Path,default=ROOT/'private/s25-analysis.json')
    run = commands.add_parser('rehearse',help='Συνθετική δοκιμή σε νέες απομονωμένες βάσεις')
    run.add_argument('--identity',default=str(Path.home()/'.config/totalaccounting/recovered-backup-age.key'))
    run.add_argument('--image',default=APP_LOCAL,help='Η ήδη ελεγμένη S24A εικόνα· χωρίς rebuild')
    run.add_argument('--source-image',default=PG15_DISCOVERY,help='Προαιρετικό καταγεγραμμένο postgres@sha256 digest για επανάληψη της ίδιας PG15 εικόνας')
    run.add_argument('--record',action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'analyse':
        source,review = read_json(args.source),read_json(args.review)
        plan = analyse(source,review,args.report)
        print(json.dumps({'status':'Analysed','source_rows':len(plan['entries']),'dispositions':plan['coverage'],
            'unresolved':len(plan['unresolved']),'report':str(output_path(args.report)),'database_changed':False},ensure_ascii=False,indent=2))
    else:
        print(json.dumps(rehearse(args),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print('S25 stopped: '+str(error) if isinstance(error,(ValueError,RuntimeError)) else 'S25 stopped: '+type(error).__name__+'; existing data retained',file=sys.stderr)
        sys.exit(1)

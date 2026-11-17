#!/usr/bin/env python3
"""Optional operator-only S26 production-image/real-broker gate. APPLY never runs it."""
import argparse
import ast
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo
from dev import ROOT, compose_environment, require_local_docker
from image import candidate_context
from verify_s05 import HIDDEN_VALUES, run

DOCS = ROOT / 'docs/implementation'


def ensure_preserved():
    manifest = json.loads((DOCS / 'evidence/S26-preserved-source.json').read_text())
    entries = manifest.get('sha256')
    if not isinstance(entries, dict) or not entries:
        raise RuntimeError('Invalid retained-source manifest')
    for name, digest in entries.items():
        if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise RuntimeError('Invalid retained-source SHA-256: ' + name)
        actual = 'sha256:' + hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != digest:
            raise RuntimeError('Retained source changed: ' + name + '; expected=' + digest + '; actual=' + actual)
    return len(entries)


def preservation_contracts():
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT/'tools'),
        '-p', 'test_s26_preservation.py'], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('S26 source-preservation contracts failed:\n' + result.stderr[-4000:])
    count = re.search(r'Ran (\d+) tests?', result.stderr + result.stdout)
    if count is None or int(count.group(1)) != 4:
        raise RuntimeError('Four source-preservation contracts must be discovered')
    return int(count.group(1))


def receipt_snapshot():
    # Operator-generated receipts have their own exact commits/formatting.
    # Preserve the operator's bytes, rather than comparing with an agent copy.
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (DOCS/'evidence').iterdir() if p.is_file() and not p.name.startswith('S26')}


def broker_gate(directory, image_id):
    identity = secrets.token_hex(10)
    project = 'accounting-s26-' + identity
    password, initial, signing = (secrets.token_urlsafe(48) for _ in range(3))
    HIDDEN_VALUES.update({password, initial, signing})
    env = {'DJANGO_SETTINGS_MODULE':'core.settings.production','DJANGO_DEBUG':'false',
        'DJANGO_SECRET_KEY':signing,'DJANGO_ALLOWED_HOSTS':'s26.example.invalid',
        'DJANGO_CSRF_TRUSTED_ORIGINS':'https://s26.example.invalid',
        'DB_NAME':'s26_'+identity,'DB_USER':'s26_app','DB_PASSWORD':password,'DB_HOST':'db','DB_PORT':'5432',
        'CELERY_BROKER_URL':'redis://redis:6379/0','BACKGROUND_JOBS_ENABLED':'true','S26_VERIFY_ID':identity}
    pins = json.loads((ROOT / 'docker/s26-image-pins.json').read_text())
    pg = json.loads((ROOT / 'docker/image-pins.json').read_text())['postgresql']['reference']
    base = {'image':image_id,'platform':'linux/amd64','environment':env,'networks':['private'],
        'read_only':True,'tmpfs':['/tmp:rw,nosuid,size=64m,mode=1777'],'cap_drop':['ALL'],
        'security_opt':['no-new-privileges:true'],'entrypoint':['python'], 'healthcheck':{'disable':True}}
    services = {
        'db':{'image':pg,'platform':'linux/amd64','environment':{'POSTGRES_PASSWORD':initial,'S26_APP_PASSWORD':password},
            'networks':['private'],'volumes':['database:/var/lib/postgresql/data'],
            'healthcheck':{'test':['CMD','pg_isready','-U','postgres'],'interval':'2s','timeout':'3s','retries':40}},
        'redis':{'image':pins['redis']['reference'],'platform':'linux/amd64','networks':['private'],
            'command':['redis-server','--protected-mode','no','--appendonly','yes','--maxmemory','96mb','--maxmemory-policy','noeviction'],
            'volumes':['broker:/data'],'healthcheck':{'test':['CMD','redis-cli','ping'],'interval':'2s','timeout':'3s','retries':40}},
        'web':dict(base),
        'worker':{**base,'command':['-m','celery','-A','core.celery:app','worker','--concurrency=1','--prefetch-multiplier=1',
            '--loglevel=WARNING','--without-gossip','--without-mingle'],'mem_limit':'512m','stop_grace_period':'75s'},
        'scheduler':{**base,'command':['-m','celery','-A','core.celery:app','beat','--loglevel=WARNING','--pidfile=',
            '--schedule=/app/run/beat/celerybeat-schedule'],'volumes':['scheduler:/app/run/beat'],'mem_limit':'192m'},
    }
    definition = {'services':services,'networks':{'private':{'internal':True}},'volumes':{'database':{},'broker':{},'scheduler':{}}}
    compose_file = directory/'compose.json'
    compose_file.write_text(json.dumps(definition))
    compose_file.chmod(0o600)
    empty_env = directory/'empty.env'; empty_env.write_text('')
    command = ['docker','compose','--file',str(compose_file),'--project-name',project,'--env-file',str(empty_env)]
    environment = {k:v for k,v in compose_environment().items() if not k.startswith(('CELERY_', 'BACKGROUND_', 'DEV_APP_', 'S26_'))}

    def compose(*args, checked=True, stdin=None, timeout=240):
        result = subprocess.run(command+list(args),cwd=ROOT,env=environment,text=True,input=stdin,
            capture_output=True,timeout=timeout)
        if checked and result.returncode:
            # Retain only a bounded redacted diagnostic, never the resolved Compose.
            from verify_s05 import redact
            raise RuntimeError('S26 Docker operation failed: '+redact(result.stderr[-2500:]))
        return result

    def manage(*args):
        return compose('run','--rm','--no-deps','-T','web','manage.py',*args)

    def probe(*args):
        result=compose('run','--rm','--no-deps','-T','--volume',str(ROOT/'tools/s26_runtime_probe.py')+':/app/s26_runtime_probe.py:ro',
            'web','/app/s26_runtime_probe.py',*args)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def healthy(timeout=90):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            status=probe('health')
            if status['status']=='ok':return status
            time.sleep(2)
        raise RuntimeError('Scheduler/worker/broker health did not converge')

    existing = subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project],env=environment,text=True)
    volumes = subprocess.check_output(['docker','volume','ls','-q','--filter','label=com.docker.compose.project='+project],env=environment,text=True)
    networks = subprocess.check_output(['docker','network','ls','-q','--filter','label=com.docker.compose.project='+project],env=environment,text=True)
    if existing.strip() or volumes.strip() or networks.strip():raise RuntimeError('Refusing existing S26 resources')
    stage='start'
    try:
        print('[S26] Απομονωμένη ουρά και βάση: '+project,flush=True)
        compose('up','--detach','--wait','--wait-timeout','180','db','redis')
        stage='restricted-database'
        sql="\\getenv pass S26_APP_PASSWORD\nCREATE ROLE s26_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pass';\nCREATE DATABASE s26_"+identity+" OWNER s26_app;\n"
        compose('exec','-T','db','psql','-U','postgres','-v','ON_ERROR_STOP=1',stdin=sql)
        manage('migrate','--noinput')
        manage('makemigrations','--check','--dry-run')
        stage='start-worker-scheduler'
        compose('up','--detach','worker','scheduler')
        healthy()
        stage='retry-and-duplicates'
        first=probe('prepare')['job_id']
        retried=probe('wait',first)
        if retried['attempts']!=2 or retried['effects']!=1:raise RuntimeError('Real retry proof failed')
        duplicate=probe('duplicates',first)
        stage='singleton-scheduler'
        second=compose('run','--rm','--no-deps','-T','scheduler',checked=False,timeout=25)
        if second.returncode==0 or 'A scheduler already owns this database' not in second.stdout+second.stderr:
            raise RuntimeError('Second scheduler did not fail specifically on database ownership')
        before=probe('scheduler-owner')['owner']
        compose('restart','scheduler')
        until=time.monotonic()+60
        while probe('scheduler-owner')['owner']==before:
            if time.monotonic()>until:raise RuntimeError('Restarted scheduler did not acquire the released lock')
            time.sleep(1)
        state=compose('exec','-T','scheduler','python','-c',"from pathlib import Path;assert list(Path('/app/run/beat').glob('celerybeat-schedule*'))")
        healthy()
        stage='broker-dispatch-failure'
        compose('stop','redis')
        pending=probe('enqueue')
        if pending['last_code']!='broker_unavailable':raise RuntimeError('Broker failure did not retain its outbox intent')
        compose('up','--detach','--wait','redis')
        manage('background_jobs','dispatch')
        recovered=probe('wait',pending['job_id'])
        stage='redis-message-loss'
        compose('stop','worker')
        lost=probe('enqueue')['job_id']
        # Only the fresh isolated Compose project may reach this deliberate loss.
        compose('exec','-T','redis','redis-cli','FLUSHDB')
        compose('up','--detach','worker')
        loss=probe('wait',lost)
        if loss['effects']!=1:raise RuntimeError('Redis-loss recovery duplicated an effect')
        stage='cancellation-and-revocation'
        compose('stop','worker')
        cancelled=probe('enqueue')['job_id'];probe('cancel',cancelled)
        revoked=probe('enqueue')['job_id'];probe('revoke')
        compose('up','--detach','worker')
        probe('wait',cancelled,'cancelled');probe('wait',revoked,'blocked')
        final=probe('final')
        health=healthy()
        ids=[line for line in compose('ps','-q','worker','scheduler').stdout.splitlines() if line]
        if len(ids)!=2:raise RuntimeError('Exactly one worker and one scheduler must be active')
        resources=[json.loads(line) for line in subprocess.check_output(['docker','stats','--no-stream','--format','{{json .}}',*ids],env=environment,text=True).splitlines()]
        return {'real_redis_retry_one_effect':True,'duplicate_delivery':duplicate,'broker_dispatch_recovered':True,
            'redis_message_loss_recovered':True,'lost_message_recovery_seconds':loss['seconds'],
            'revocation_blocks_execution':True,'cancellation_blocks_execution':True,'second_scheduler_rejected':True,
            'scheduler_restart_and_retained_state':True,'restricted_role_migrations':True,'same_image_services':True,
            'queue_health':health,'worker_concurrency':1,'resource_sample':[{'name':r.get('Name'),'memory':r.get('MemUsage'),'cpu':r.get('CPUPerc')} for r in resources],
            'final':final,'redis_image':pins['redis']['reference']}
    except Exception as error:
        print('S26-DIAG '+json.dumps({'stage':stage,'error':type(error).__name__}),file=sys.stderr,flush=True)
        raise
    finally:
        cleanup=compose('down','--volumes','--remove-orphans',checked=False)
        remaining=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project],env=environment,text=True)
        left_volumes=subprocess.check_output(['docker','volume','ls','-q','--filter','label=com.docker.compose.project='+project],env=environment,text=True)
        if cleanup.returncode or remaining.strip() or left_volumes.strip():
            raise RuntimeError('S26 cleanup incomplete; inspect only the reported isolated project')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record',action='store_true')
    parser.add_argument('--image',help='Optional exact local production image with matching committed context')
    args=parser.parse_args()
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():
            raise RuntimeError('Commit source/evidence before S26 verification')
        preserved_count = ensure_preserved()
        preservation_tests = preservation_contracts()
        print('[S26] Διατήρηση '+str(preserved_count)+' αρχείων και '+str(preservation_tests)+' έλεγχοι ακεραιότητας επιβεβαιώθηκαν.', flush=True)
        require_local_docker()
        receipts=receipt_snapshot()
        before=candidate_context()[1]['digest']
        print('[S26] Πλήρης έλεγχος της νέας εικόνας και των προηγούμενων οικονομικών δοκιμών.',flush=True)
        with tempfile.TemporaryDirectory(prefix='accounting-s26-') as tmp:
            directory=Path(tmp)
            # The continuing gate supplies hash-lock/catalog/secret/context and full image checks.
            delivery_path=directory/'delivery.json'
            call=[sys.executable,str(ROOT/'tools/verify_delivery.py'),'--report',str(delivery_path)]
            if args.image:call+=['--image',args.image]
            subprocess.run(call,cwd=ROOT,check=True)
            delivery=json.loads(delivery_path.read_text())
            image=delivery['image']
            suite=delivery['suite']
            count=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in ast.walk(ast.parse((ROOT/'accounting/tests_background_jobs.py').read_text())))
            if suite['tests_run']!=661+count or suite['known_failures_reproduced'] or any(suite[k] for k in ('unexpected_errors','unexpected_failures','unexpected_successes','skips')):
                raise RuntimeError('The full 661 retained tests and new S26 contracts must all pass')
            if len(suite['cases'])!=36 or any(c['outcome']!='passed' for c in suite['cases']):
                raise RuntimeError('Every retained financial case must pass')
            proof=broker_gate(directory,image['image_id'])
        ensure_preserved()
        if receipts!=receipt_snapshot():
            raise RuntimeError('A retained local historical receipt changed during verification')
        if before!=candidate_context()[1]['digest'] or subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():
            raise RuntimeError('Source changed during operator verification')
        report={'step':'S26','status':'Verified','scope':'isolated-production-image-and-real-redis-jobs',
            'verified_at':datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
            'source_commit':'git:'+subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'application_context_digest':before,'suite':suite,'s26_test_methods':count,'image':image,
            'retained_source_files_checked':preserved_count,'preservation_guard_tests_passed':preservation_tests,
            'retained_source_files_checked':preserved_count,'source_preservation_contracts_passed':preservation_tests,
            'agent_tests_builds_docker_migrations_run':False,'docker_execution_by_operator':True,
            'local_demo_or_vm_changed':False,'human_accounts_or_mfa_changed':False,
            'full_requirement_acceptance':'Pending','d05_real_migration_review':'Pending','g2_release_acceptance':'Pending',
            'owned_resources_removed':True,**proof}
        if args.record:
            from prepare_s26 import record_result
            record_result(report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except (RuntimeError,OSError,ValueError,subprocess.SubprocessError,AssertionError) as error:
        parser.exit(1,'S26 stopped: '+str(error)+'\n')


if __name__=='__main__':main()

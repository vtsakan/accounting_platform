"""Operator-only extension of the retained S26 real-broker gate, fresh resources."""
import json,secrets,subprocess,sys,time
from dev import ROOT,compose_environment
from verify_s05 import HIDDEN_VALUES

def broker_gate(directory, image_id):
    identity = secrets.token_hex(10)
    project = 'accounting-s28-' + identity
    password, initial, signing = (secrets.token_urlsafe(48) for _ in range(3))
    HIDDEN_VALUES.update({password, initial, signing})
    env = {'DJANGO_SETTINGS_MODULE':'core.settings.production','DJANGO_DEBUG':'false',
        'DJANGO_SECRET_KEY':signing,'DJANGO_ALLOWED_HOSTS':'s26.example.invalid',
        'DJANGO_CSRF_TRUSTED_ORIGINS':'https://s26.example.invalid',
        'DB_NAME':'s26_'+identity,'DB_USER':'s26_app','DB_PASSWORD':password,'DB_HOST':'db','DB_PORT':'5432',
        'CELERY_BROKER_URL':'redis://redis:6379/0','BACKGROUND_JOBS_ENABLED':'true','FEE_AUTOMATION_ENABLED':'true','S26_VERIFY_ID':identity,'S28_VERIFY_ID':identity}
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
        'worker':{**base,'command':['-m','celery','-A','core.celery:app','worker','--concurrency=1','--include=s28_ack_probe','--prefetch-multiplier=1',
            '--loglevel=WARNING','--without-gossip','--without-mingle'],'volumes':[str(ROOT/'tools/s28_ack_probe.py')+':/app/s28_ack_probe.py:ro'],'mem_limit':'512m','stop_grace_period':'75s'},
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

    def fee_probe(*args):
        result=compose('run','--rm','--no-deps','-T','--volume',str(ROOT/'tools/s28_runtime_probe.py')+':/app/s28_runtime_probe.py:ro',
            'web','/app/s28_runtime_probe.py',*args)
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
        print('[S28] Απομονωμένη ουρά και βάση: '+project,flush=True)
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
        stage='s28-real-automatic-generation'
        fee_probe('prepare')
        automatic=fee_probe('wait-auto')
        stage='s28-charge-commit-before-ack-worker-loss'
        fee_probe('ack-prepare')
        ack=fee_probe('wait-ack')
        stage='s28-generation-authority-and-cash-reconciliation'
        fees=fee_probe('final')
        final=probe('final')
        health=healthy()
        ids=[line for line in compose('ps','-q','worker','scheduler').stdout.splitlines() if line]
        if len(ids)!=2:raise RuntimeError('Exactly one worker and one scheduler must be active')
        resources=[json.loads(line) for line in subprocess.check_output(['docker','stats','--no-stream','--format','{{json .}}',*ids],env=environment,text=True).splitlines()]
        return {'s28_generation':{'automatic':automatic,'commit_before_ack':ack,'reconciliation':fees},'real_redis_retry_one_effect':True,'duplicate_delivery':duplicate,'broker_dispatch_recovered':True,
            'redis_message_loss_recovered':True,'lost_message_recovery_seconds':loss['seconds'],
            'revocation_blocks_execution':True,'cancellation_blocks_execution':True,'second_scheduler_rejected':True,
            'scheduler_restart_and_retained_state':True,'restricted_role_migrations':True,'same_image_services':True,
            'queue_health':health,'worker_concurrency':1,'resource_sample':[{'name':r.get('Name'),'memory':r.get('MemUsage'),'cpu':r.get('CPUPerc')} for r in resources],
            'final':final,'redis_image':pins['redis']['reference']}
    except Exception as error:
        print('S28-BROKER-DIAG '+json.dumps({'stage':stage,'error':type(error).__name__}),file=sys.stderr,flush=True)
        raise
    finally:
        cleanup=compose('down','--volumes','--remove-orphans',checked=False)
        remaining=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project],env=environment,text=True)
        left_volumes=subprocess.check_output(['docker','volume','ls','-q','--filter','label=com.docker.compose.project='+project],env=environment,text=True)
        if cleanup.returncode or remaining.strip() or left_volumes.strip():
            raise RuntimeError('S26 cleanup incomplete; inspect only the reported isolated project')

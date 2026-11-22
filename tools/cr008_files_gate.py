"""Actual scanner/restricted PG17/encrypted file recovery. Run only by operator."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

from dev import ROOT,compose_environment
from verify_s05 import HIDDEN_VALUES,redact


def files_gate(directory,image_id,*,host_dns=False):
    identity=secrets.token_hex(10);project='accounting-cr008-'+identity
    password,initial,signing=(secrets.token_urlsafe(48) for _ in range(3))
    HIDDEN_VALUES.update({password,initial,signing})
    recovery=Path.home()/'.config/totalaccounting/attachment-rehearsals'/identity
    recovery.mkdir(mode=0o700,parents=True,exist_ok=False)
    signing_file=recovery/'application-key'
    with signing_file.open('x') as stream:stream.write(signing+'\n')
    signing_file.chmod(0o600)
    pin=json.loads((ROOT/'docker/attachment-scanner-pin.json').read_text())
    pg=json.loads((ROOT/'docker/image-pins.json').read_text())['postgresql']['reference']
    environment=compose_environment()
    env={'DJANGO_SETTINGS_MODULE':'core.settings.production','DJANGO_DEBUG':'false','DJANGO_SECRET_KEY':signing,
        'DJANGO_ALLOWED_HOSTS':'cr008.example.invalid','DJANGO_CSRF_TRUSTED_ORIGINS':'https://cr008.example.invalid',
        'DB_NAME':'cr008_'+identity,'DB_USER':'cr008_app','DB_PASSWORD':password,'DB_HOST':'db','DB_PORT':'5432',
        'ATTACHMENT_SCANNER_HOST':'scanner','CR008_VERIFY_ID':identity}
    definition={'services':{
        'db':{'image':pg,'platform':'linux/amd64','environment':{'POSTGRES_PASSWORD':initial,'CR008_APP_PASSWORD':password},
            'networks':['private'],'volumes':['database:/var/lib/postgresql/data'],
            'healthcheck':{'test':['CMD','pg_isready','-U','postgres'],'interval':'2s','timeout':'3s','retries':40}},
        'definitions':{'image':pin['reference'],'platform':'linux/amd64','networks':['definitions'],
            'mem_limit':'4096m','security_opt':['no-new-privileges:true'],
            'volumes':['signatures:/var/lib/clamav',str(ROOT/'docker/attachment-freshclam.conf')+':/etc/clamav/cr008-freshclam.conf:ro'],
            'entrypoint':['/bin/sh','-ec'],'command':['mkdir -p /var/lib/clamav; chown clamav:clamav /var/lib/clamav; exec freshclam --stdout --config-file=/etc/clamav/cr008-freshclam.conf']},
        'scanner':{'image':pin['reference'],'platform':'linux/amd64','networks':['private'],
            'mem_limit':'4096m','cpus':2,'security_opt':['no-new-privileges:true'],
            'volumes':['signatures:/var/lib/clamav',str(ROOT/'docker/attachment-clamd.conf')+':/etc/clamav/cr008.conf:ro'],
            'entrypoint':['clamd','--foreground','--config-file=/etc/clamav/cr008.conf']},
        'app':{'image':image_id,'platform':'linux/amd64','environment':env,'networks':['private'],
            'read_only':True,'tmpfs':['/tmp:rw,noexec,nosuid,size=128m,mode=1777'],'mem_limit':'1024m',
            'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'entrypoint':['python'],
            'healthcheck':{'disable':True}},
        },'networks':{'private':{'internal':True},'definitions':{}},'volumes':{'database':{},'signatures':{}}}
    if host_dns:
        service=definition['services']['definitions'];service.pop('networks');service['network_mode']='host'
        service['volumes'].append('/etc/resolv.conf:/etc/resolv.conf:ro')
    compose_file=directory/'files-compose.json';compose_file.write_text(json.dumps(definition));compose_file.chmod(0o600)
    empty=directory/'files-empty.env';empty.write_text('')
    command=['docker','compose','--file',str(compose_file),'--project-name',project,'--env-file',str(empty)]
    stage='initialise'

    def compose(*args,stdin=None,binary=False,timeout=180,checked=True):
        result=subprocess.run(command+list(args),input=stdin,cwd=ROOT,env=environment,
            capture_output=True,text=not binary,timeout=timeout)
        if checked and result.returncode:
            output=result.stdout[-1500:]+result.stderr[-2500:]
            if isinstance(output,bytes):output=output.decode(errors='replace')
            raise RuntimeError('CR008 file gate failed at '+stage+': '+redact(output))
        return result

    def app(*args,overrides=(),timeout=180):
        return compose('run','--rm','--no-deps','-T',*overrides,'app',*args,timeout=timeout)

    def probe(action,overrides=()):
        result=app('/app/cr008_probe.py',action,overrides=('--volume',str(ROOT/'tools/cr008_runtime_probe.py')+':/app/cr008_probe.py:ro',*overrides),timeout=240)
        return json.loads(result.stdout.strip().splitlines()[-1])

    for kind in ('container','volume','network'):
        args=['docker',{'container':'ps','volume':'volume','network':'network'}[kind]]
        if kind=='container':args+=['-aq']
        else:args+=['ls','-q']
        existing=subprocess.check_output(args+['--filter','label=com.docker.compose.project='+project],env=environment,text=True)
        if existing.strip():raise RuntimeError('Refusing existing file verification resources')
    owned=False
    try:
        print('[CR008] Απομονωμένος έλεγχος πραγματικών αρχείων και επαναφοράς: '+project,flush=True)
        owned=True;compose('up','--detach','--wait','--wait-timeout','180','db')
        stage='restricted-role'
        sql="\\getenv pass CR008_APP_PASSWORD\nCREATE ROLE cr008_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pass';\nCREATE DATABASE cr008_"+identity+" OWNER cr008_app;\nCREATE DATABASE cr008_"+identity+"_recovered OWNER cr008_app;\n"
        compose('exec','-T','db','psql','-U','postgres','-v','ON_ERROR_STOP=1',stdin=sql)
        app('manage.py','migrate','--noinput');app('manage.py','makemigrations','--check','--dry-run')
        stage='real-antivirus-start'
        print('[CR008] Πραγματικός έλεγχος ασφαλείας: αρχικοποίηση υπογραφών, όριο μνήμης 4 GiB.',flush=True)
        compose('run','--rm','--no-deps','-T','definitions',timeout=900)
        compose('up','--detach','scanner',timeout=900)
        until=time.monotonic()+900
        code="import socket; s=socket.create_connection(('scanner',3310),2); s.sendall(b'zPING\\0'); assert s.recv(20).rstrip(b'\\0\\n')==b'PONG'; s.close()"
        while time.monotonic()<until:
            result=compose('run','--rm','--no-deps','-T','app','-c',code,timeout=15,checked=False)
            if result.returncode==0:break
            print('[CR008] Αναμονή ετοιμότητας ελέγχου αρχείων...',flush=True);time.sleep(10)
        else:
            logs=compose('logs','--tail','35','scanner',checked=False)
            raise RuntimeError('Scanner readiness failed: '+redact(logs.stdout[-3000:]))
        stage='real-upload-formats-and-denials';prepared=probe('prepare');before=probe('recovered')
        stage='encrypted-backup'
        dump=compose('exec','-T','db','pg_dump','-U','cr008_app','--format=custom','--no-owner','--no-privileges','cr008_'+identity,binary=True).stdout
        key_path=recovery/'age.identity'
        generated=subprocess.run(['age-keygen','-o',str(key_path)],capture_output=True,text=True,check=True);key_path.chmod(0o600)
        recipient=subprocess.check_output(['age-keygen','-y',str(key_path)],text=True).strip()
        archive=recovery/'client-files.dump.age'
        subprocess.run(['age','-r',recipient,'-o',str(archive)],input=dump,capture_output=True,check=True)
        archive.chmod(0o600);del dump
        stage='restore-recovered-key-and-database'
        recovered_dump=subprocess.check_output(['age','-d','-i',str(key_path),str(archive)])
        compose('exec','-T','db','pg_restore','-U','cr008_app','--exit-on-error','--no-owner','--no-privileges',
            '--dbname=cr008_'+identity+'_recovered',stdin=recovered_dump,binary=True)
        del recovered_dump
        recovered_key=signing_file.read_text().strip()
        overrides=('--env','DB_NAME=cr008_'+identity+'_recovered','--env','DJANGO_SECRET_KEY='+recovered_key)
        restored=probe('recovered',overrides)
        if restored!=before or probe('snapshot')!=prepared['snapshot']:raise RuntimeError('Restored tables/files do not exactly match')
        stage='completed'
        return {'formats_verified':list(prepared['formats']),'original_file_sha256_after_authenticated_download':True,
            'antivirus_real_eicar_denied':True,'scanner_unavailable_denied_without_storage':True,
            'restricted_role_migrations':True,'sealed_bytes_in_database':True,'all_public_tables_restored':len(before['snapshot']),
            'restored_files':before['files'],'all_public_tables_and_file_hashes_matched':True,'wrong_recovery_key_denied':True,
            'separate_external_recovery_material_used':True,'encrypted_recovery_archive':str(archive),
            'scanner_image':pin['reference'],'scanner_memory_cap_mib':4096,'owned_resources_removed':True,
            'plaintext_archives_written':False,'real_client_data':False,'vm_changed':False}
    finally:
        if owned:
            result=compose('down','--volumes','--remove-orphans',timeout=120,checked=False)
            if result.returncode:raise RuntimeError('Owned file-verification resources were not fully removed')

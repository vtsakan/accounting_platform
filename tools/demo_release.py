#!/usr/bin/env python3
"""Laptop commands for the selected S14 VM demo; identities stay outside Git/VM."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPCookieProcessor
from urllib.parse import urlencode
from http.cookiejar import CookieJar

from cloud import require
import image
import preview as publisher
import preview_common as common
import operations_common as operations
import demo_release_common as policy

policy.register_diagnostics()

CONFIG=common.ROOT/'private/demo-release.json'
REMOTE='accounting-demo-stage'


def load():return json.loads(CONFIG.read_text())


def gcloud(config,*arguments,json_output=False):
    return publisher.gcloud(config,*arguments,json_output=json_output)


def ssh(config,command,json_output=True):
    gcp=config['gcp']
    return gcloud(config,'compute','ssh',gcp['ssh_user']+'@'+gcp['vm_name'],'--zone='+gcp['zone'],
        '--tunnel-through-iap','--command='+command,json_output=json_output)


def context_gate():
    revision,_,context=image.committed_context()
    require(not subprocess.check_output(['git','status','--porcelain'],cwd=common.ROOT).strip(),'Commit source/evidence and move private files outside Git first')
    report=json.loads((common.ROOT/'docs/implementation/evidence/S14-verification.json').read_text())
    require(report['status']=='Verified' and report['docker_execution'] is True and report.get('referrer_regression_tests')==9,
            'Complete and commit the corrected S14 Docker gate first')
    require(report['application_context_digest']==context['digest'],'S14 evidence belongs to different application bytes')
    return revision,context


def configure(operator,office_name):
    context_gate()
    require(not CONFIG.exists(),'A demo release configuration exists; inspect/reuse it')
    local=common.validate(json.loads((common.ROOT/'private/preview.json').read_text()),published=True)
    source=common.validate(ssh(local,'sudo -n cat /etc/accounting/preview.json'),published=True)
    old_operations=operations.validate(json.loads((common.ROOT/'private/operations.json').read_text()),local=True)
    require(old_operations['preview']==source,'Local S10 recovery binding differs from the installed VM; inspect before configuring')
    target=deepcopy(source)
    target['db_name']='accounting_demo_'+secrets.token_hex(6)
    target['published']=None;target.pop('deployment_commit',None)
    require(operator.strip() and office_name.startswith('Δοκιμαστικό '),'Name the operator and sample office')
    config={'source':source,'target':target,'operator':operator,'office_name':office_name,'old_local_operations':old_operations}
    common.private_json(CONFIG,config,exclusive=True)
    return {'status':'Configured','private_config':str(CONFIG),'source_database':source['db_name'],'target_database':target['db_name'],'cloud_changed':False}


def publish(config):
    context_gate()
    path=common.ROOT/'private/demo-preview.json';common.private_json(path,config['target'])
    result=publisher.publish(config['target'],path,common.ROOT/'private/demo-delivery.json')
    config['target']=json.loads(path.read_text());common.private_json(CONFIG,config)
    return result


def stage(config):
    revision,context=context_gate()
    target=config['target'];common.validate(target,published=True)
    require(target['published']['context_digest']==context['digest'],'Published image differs from verified source')
    target['deployment_commit']=revision
    common.private_json(CONFIG,config)
    with tempfile.TemporaryDirectory(prefix='accounting-demo-stage-') as temporary:
        stage=Path(temporary)/REMOTE;(stage/'tools').mkdir(parents=True);(stage/'docs/implementation').mkdir(parents=True)
        bundle=stage/'source.tar';bundle.write_bytes(common.run(['git','archive','--format=tar',revision]))
        names=('demo_release_host','demo_release_common','preview_common','preview_host','preview_events','cloud',
            'operations_common','operations_host','operations_pg','image','static_export','dev','verify_s05','init_local_env')
        for name in names:(stage/'tools'/(name+'.py')).write_bytes(common.run(['git','show',revision+':tools/'+name+'.py']))
        inventory='docs/implementation/cloud_inventory.json'
        (stage/inventory).write_bytes(common.run(['git','show',revision+':'+inventory]))
        common.private_json(stage/'input.json',{'source':config['source'],'target':target,'operator':config['operator'],
            'office_name':config['office_name'],'bundle_sha256':common.file_sha(bundle)})
        gcp=target['gcp'];remote=gcp['ssh_user']+'@'+gcp['vm_name']
        ssh(target,'umask 077; mkdir -p '+REMOTE,json_output=False)
        gcloud(target,'compute','scp','--recurse',stage,remote+':~/','--zone='+gcp['zone'],'--tunnel-through-iap')
    result=host_action(config,'plan', '--input',REMOTE+'/input.json','--bundle',REMOTE+'/source.tar')
    common.private_json(common.ROOT/'private/demo-plan.json',result)
    return result


def host_action(config,action,*arguments):
    command=shlex.join(['sudo','-n','python3',REMOTE+'/tools/demo_release_host.py',action,*arguments])
    return ssh(config['target'],command)


def synchronize(config,state):
    require(state['target']==config['target'] and state['original_database_unchanged'],'VM target/source identity differs')
    rebound=deepcopy(config['old_local_operations']);rebound.update(state['operations'])
    rebound['local_identity']=config['old_local_operations']['local_identity']
    operations.validate(rebound,local=True)
    common.private_json(common.ROOT/'private/demo-operations.json',rebound)
    return rebound


def public_checks(hostname):
    jar=CookieJar();client=build_opener(HTTPCookieProcessor(jar));base='https://'+hostname
    with client.open(base+'/health/ready/',timeout=20) as response:
        require(response.status==200 and json.load(response)=={'status':'ready'},'Public readiness did not pass')
    with client.open(base+'/login/',timeout=20) as response:
        body=response.read().decode()
        require(response.status==200 and 'Σύνδεση στην εφαρμογή' in body and response.headers['Referrer-Policy']=='same-origin','Greek login/form policy differs')
        token=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',body).group(1)
    data={'username':'s14_demo_probe_'+secrets.token_hex(6),'password':secrets.token_urlsafe(32),'csrfmiddlewaretoken':token}
    def post(origin,values):
        request=Request(base+'/login/',data=urlencode(values).encode(),headers={'Origin':origin,'Content-Type':'application/x-www-form-urlencoded'})
        try:return client.open(request,timeout=20)
        except HTTPError as error:return error
    with post(base,data) as response:require(response.status==200,'Same-origin login POST was blocked')
    for origin in ('null','https://foreign.example.invalid'):
        with post(origin,data) as response:require(response.status==403,'Untrusted Origin was accepted')
    with post(base,{**data,'csrfmiddlewaretoken':''}) as response:require(response.status==403,'Missing CSRF token was accepted')
    return {'public_https_readiness':True,'greek_login':True,'same_origin_form_post':True,'null_foreign_origin_denied':True,'missing_csrf_denied':True,
        'certificate_chain_and_hostname_verified':True,'actual_browser_mfa_acceptance':'Pending operator login'}


def restore(config,identity):
    state=host_action(config,'status');require(state['status']=='awaiting_off_vm_restore','VM demo is not awaiting recovery proof')
    rebound=synchronize(config,state)
    from operations_recovery import restore as recover
    result=recover(rebound,state['after_backup'],identity)
    result['public_checks']=public_checks(config['target']['hostname'])
    result['target_image']=config['target']['published']['image'];result['office_id']=state['office_id']
    common.private_json(common.ROOT/'private/demo-restore.json',result)
    result['vm_attestation']=host_action(config,'confirm-restore','--receipt-sha256',result['receipt']['sha256'])
    return result


def bootstrap(config,username,email):
    state=host_action(config,'status');proof=json.loads((common.ROOT/'private/demo-restore.json').read_text())
    require(state['status']=='demo_ready' and proof['status']=='Restored' and proof['target_image']==config['target']['published']['image'] and
        proof['office_id']==state['office_id'] and state['original_database_unchanged'],'Complete the new demo backup restore first')
    require(re.fullmatch(r'[\w.@+-]{1,150}',username),'Invalid username')
    from email.utils import parseaddr
    require(parseaddr(email)[1]==email and '@' in email and '\n' not in email,'Invalid account email')
    command=shlex.join(['sudo','-n','docker','exec','-it','accounting-preview-web-1','python','manage.py','bootstrap_office_owner',
        '--office',state['office_id'],'--username',username,'--email',email,'--operator',config['operator']])
    p=config['target']['gcp']
    result=subprocess.run(['gcloud','compute','ssh',p['ssh_user']+'@'+p['vm_name'],'--project='+p['project_id'],'--zone='+p['zone'],
        '--tunnel-through-iap','--ssh-flag=-t','--command='+command],env={**__import__('os').environ,'CLOUDSDK_CORE_LOG_HTTP':'false'})
    require(result.returncode==0,'VM account creation stopped; no account password was returned to this tool')
    return {'status':'Account bootstrap completed','username':username,'url':'https://'+config['target']['hostname']+'/login/','mfa':'Complete enrollment in your browser; keep recovery codes outside Git'}


def invitation(config,username,email):
    state=host_action(config,'status')
    require(state['status']=='demo_ready' and state['original_database_unchanged'],'Complete the demo deployment/recovery gate first')
    code=common.run(['git','show',common.deployment_commit(config['target'])+':tools/demo_invitation.py']).decode()
    command=shlex.join(['sudo','-n','docker','exec','-it','accounting-preview-web-1','python','-c',code,username,email,state['office_id']])
    p=config['target']['gcp']
    result=subprocess.run(['gcloud','compute','ssh',p['ssh_user']+'@'+p['vm_name'],'--project='+p['project_id'],'--zone='+p['zone'],
        '--tunnel-through-iap','--ssh-flag=-t','--command='+command],env={**__import__('os').environ,'CLOUDSDK_CORE_LOG_HTTP':'false'})
    require(result.returncode==0,'Invitation capture stopped; no external message was sent')
    return {'status':'Invitation captured in your operator terminal','live_mail_sent':False,'next':'Recipient registers through the HTTPS link; owner approves in Συνεργάτες'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('configure','publish','plan','apply','status','restore','bootstrap','invite','rollback'))
    parser.add_argument('--operator',default='vtsakan');parser.add_argument('--office-name',default='Δοκιμαστικό λογιστικό γραφείο')
    parser.add_argument('--plan-sha256');parser.add_argument('--identity',type=Path)
    parser.add_argument('--username',default='vtsakan');parser.add_argument('--email')
    args=parser.parse_args()
    try:
        if args.action=='configure':result=configure(args.operator,args.office_name)
        else:
            config=load()
            if args.action=='publish':result=publish(config)
            elif args.action=='plan':result=stage(config)
            elif args.action=='apply':
                require(args.plan_sha256,'Pass the hash of the reviewed two-record plan')
                result=host_action(config,'apply','--plan-sha256',args.plan_sha256)
                common.private_json(common.ROOT/'private/demo-deployment.json',result)
                synchronize(config,host_action(config,'status'))
            elif args.action=='restore':
                require(args.identity,'Pass your separately recovered age key, outside Git')
                result=restore(config,args.identity)
            elif args.action=='bootstrap':
                require(args.email,'Pass the email for this regular application account')
                result=bootstrap(config,args.username,args.email)
            elif args.action=='invite':
                require(args.email,'Pass the invited demo recipient email')
                result=invitation(config,args.username,args.email)
            else:result=host_action(config,args.action)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as error:
        message=str(error) if type(error) in {ValueError,RuntimeError} else type(error).__name__
        parser.exit(1,'Demo release stopped: '+message+'\n')


if __name__=='__main__':main()

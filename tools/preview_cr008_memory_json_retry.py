#!/usr/bin/env python3
"""Retarget only the unstarted CR008 memory plan rejected on Compose JSON types."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess

import preview_cr008_memory_release as release
from r1_gate import digest_bytes, require

PRIOR_SOURCE='docs/implementation/evidence/CR008-4GB-MEMORY-json-prior-source.json'
REJECTED_DEPLOYMENT='git:27b7fc8b415454f45c881f3c4beda8fc2f29beae'


def corrected_config(config,revision):
    require(config.get('profile')==release.policy.PROFILE,'Retain the separate scheduler memory profile')
    require(type(revision) is str and re.fullmatch(r'[0-9a-f]{40}',revision) is not None,
        'A complete committed correction revision is required')
    release.policy.transition(config['source'],config['target'])
    result=deepcopy(config);result['target']['deployment_commit']=revision
    release.policy.transition(result['source'],result['target'])
    return result


def planned_only(value):
    require(value.get('status')=='Planned'
        and type(value.get('schema_before')) is int and value['schema_before']==36
        and type(value.get('schema_after')) is int and value['schema_after']==36
        and value.get('same_current_database') is True
        and value.get('database_cloned_or_migrated') is False
        and value.get('services_restarted') is False
        and type(value.get('plan_sha256')) is str
        and re.fullmatch(r'sha256:[0-9a-f]{64}',value['plan_sha256']) is not None,
        'Only a successful guarded unstarted same-database memory plan may retarget the configuration')


def retarget(identity):
    revision=release.source_gate()
    require(release.CONFIG.is_file() and not release.CONFIG.is_symlink(),
        'Retain the existing unstarted memory configuration as a regular private file')
    before=release.CONFIG.read_bytes();config=release.load()
    old_revision=config['target']['deployment_commit']
    release.previous.git('merge-base','--is-ancestor',old_revision,revision)
    retained=release.common.run(['git','show',old_revision+':'+str(release.SOURCE.relative_to(release.ROOT))],
        environment=release.image.git_environment())
    if retained==release.SOURCE.read_bytes():
        return {'status':'Corrected configured revision retained','deployment_commit':'git:'+old_revision}
    require('git:'+old_revision==REJECTED_DEPLOYMENT
        and retained==(release.ROOT/PRIOR_SOURCE).read_bytes(),
        'The pending configuration is not the exact observed JSON-rejected revision; it was retained')
    candidate=corrected_config(config,revision)
    operations=release.previous.ssh(config['source'],'sudo -n cat /etc/accounting/operations.json')
    require(operations['preview']==config['source'],'The current active deployment changed')
    release.previous.recovery_config(operations,identity)
    require(release.host_action(config,'status').get('status')=='Not applied',
        'A memory journal already exists; retain its configuration and inspect its recovery path')
    # The host plan takes the existing lock and rejects any STATE/HOLD before
    # validating the actual source/database, retained failed journal and limits.
    # No prepare, activation, writer stop or database migration is invoked here.
    release.transfer(candidate)
    print('[CR008-MEMORY] Έλεγχος διορθωμένου Compose JSON πριν από τη σύνδεση της εκκρεμούς ρύθμισης.',flush=True)
    result=release.host_action(candidate,'plan','--input',release.STAGE+'/input.json',
        '--bundle',release.STAGE+'/source.tar')
    planned_only(result)
    require(release.host_action(candidate,'status').get('status')=='Not applied',
        'A memory attempt started concurrently; the pending configuration was retained')
    require(release.source_gate()==revision and release.CONFIG.read_bytes()==before
        and release.load()==config,
        'Local source/configuration changed concurrently; no retarget was written')
    backup=release.CONFIG.with_name('vm-cr008-4gb-memory-before-json-'+digest_bytes(before)[7:23]+'.json')
    if backup.exists() or backup.is_symlink():
        require(backup.is_file() and not backup.is_symlink() and backup.read_bytes()==before,
            'The exclusive pending-configuration backup differs; it was not overwritten')
    else:
        descriptor=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(before);stream.flush();os.fsync(stream.fileno())
    release.common.private_json(release.CONFIG,candidate)
    return {'status':'Unstarted memory profile retargeted after guarded plan',
        'deployment_commit':'git:'+revision,'previous_pending_commit':'git:'+old_revision,
        'same_current_database':True,'services_restarted':False,
        'old_completed_and_failed_journals_changed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity',type=Path,default=Path.home()/'.config/totalaccounting/recovered-backup-age.key')
    args=parser.parse_args();os.chdir(release.ROOT)
    try:print(json.dumps(retarget(args.identity),ensure_ascii=False,indent=2))
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        reason=str(error) if isinstance(error,RuntimeError) else 'Memory JSON retry stopped; private input/provider output omitted'
        parser.exit(1,'CR008-MEMORY JSON retry stopped: '+reason+'\n')


if __name__=='__main__':main()

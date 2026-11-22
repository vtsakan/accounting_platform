#!/usr/bin/env python3
"""Explicitly retarget only an unstarted CR008 plan after its duration correction."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess

import preview_cr008_profile_release as release
import preview_cr008_profile_policy as policy
from r1_gate import digest_bytes, require

PRIOR_SOURCE = 'docs/implementation/evidence/CR008-4GB-duration-prior-source.json'


def corrected_config(config, revision):
    require(config.get('profile')==policy.PROFILE,'Retain the separate existing-database profile')
    require(re.fullmatch(r'[0-9a-f]{40}',revision) is not None,'A complete committed correction revision is required')
    policy.transition(config['source'],config['target'])
    result=deepcopy(config);result['target']['deployment_commit']=revision
    policy.transition(result['source'],result['target'])
    return result


def planned_only(value):
    require(value.get('status')=='Planned' and value.get('schema_before')==value.get('schema_after')==36
        and value.get('same_current_database') is True
        and value.get('database_cloned_or_migrated') is False
        and value.get('services_restarted') is False
        and re.fullmatch(r'sha256:[0-9a-f]{64}',value.get('plan_sha256','')) is not None,
        'Only a successful guarded same-database plan may retarget this unstarted attempt')


def retarget(identity):
    revision=release.source_gate()
    before=release.CONFIG.read_bytes();config=release.load()
    old_revision=config['target']['deployment_commit']
    release.previous.git('merge-base','--is-ancestor',old_revision,revision)
    retained=release.common.run(['git','show',old_revision+':'+str(release.SOURCE.relative_to(release.ROOT))],
        environment=release.image.git_environment())
    if retained==release.SOURCE.read_bytes():
        return {'status':'Corrected configured revision retained','deployment_commit':'git:'+old_revision}
    require(retained==(release.ROOT/PRIOR_SOURCE).read_bytes(),
        'The pending target is not the exact earlier duration preparation; its configuration was retained')
    candidate=corrected_config(config,revision)
    operations=release.previous.ssh(config['source'],'sudo -n cat /etc/accounting/operations.json')
    require(operations['preview']==config['source'],'The current active deployment changed')
    release.previous.recovery_config(operations,identity)
    require(release.host_action(config,'status').get('status')=='Not applied',
        'A profile journal already exists; retain its configuration and use its recovery path')
    # The unchanged host plan owns the existing lock and rejects STATE/HOLD.
    # It validates the current source/database/image and corrected Compose before
    # any local retarget. No prepare/activate or database migration is invoked.
    release.transfer(candidate)
    print('[CR008-4GB] Έλεγχος διορθωμένου plan πριν από τη σύνδεση της εκκρεμούς ρύθμισης.',flush=True)
    result=release.host_action(candidate,'plan','--input',release.STAGE+'/input.json',
        '--bundle',release.STAGE+'/source.tar')
    planned_only(result)
    require(release.host_action(candidate,'status').get('status')=='Not applied',
        'A profile attempt started concurrently; the pending configuration was retained')
    require(release.source_gate()==revision and release.CONFIG.read_bytes()==before,
        'Local source/configuration changed concurrently; no retarget was written')
    backup=release.CONFIG.with_name('vm-cr008-4gb-profile-before-duration-'+digest_bytes(before)[7:23]+'.json')
    if backup.exists() or backup.is_symlink():
        require(backup.is_file() and not backup.is_symlink() and backup.read_bytes()==before,
            'The exclusive pending-configuration backup differs; it was not overwritten')
    else:
        descriptor=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(before);stream.flush();os.fsync(stream.fileno())
    release.common.private_json(release.CONFIG,candidate)
    return {'status':'Unstarted profile retargeted after guarded plan','deployment_commit':'git:'+revision,
        'previous_pending_commit':'git:'+old_revision,'same_current_database':True,
        'legacy_completed_configuration_changed':False,'services_restarted':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity',type=Path,default=Path.home()/'.config/totalaccounting/recovered-backup-age.key')
    args=parser.parse_args();os.chdir(release.ROOT)
    try:print(json.dumps(retarget(args.identity),ensure_ascii=False,indent=2))
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        reason=str(error) if isinstance(error,RuntimeError) else 'Profile retry stopped; private input/provider output omitted'
        parser.exit(1,'CR008-4GB retry stopped: '+reason+'\n')


if __name__=='__main__':main()

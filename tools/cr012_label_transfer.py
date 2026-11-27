"""Bound evidence closure and a narrowly guarded, unstarted deployment retarget."""
from copy import deepcopy
import re

import preview_cr012_label_policy as policy
from r1_gate import require

FAILED_COMMIT='f5ccfa463d4afda2ba30109ea13981ea47e0a1ba'  # pragma: allowlist secret -- actual operator/public pending deployment
OLD_MANIFEST='sha256:9354e964d27eb693028d5a7de0fd8b7efa19b123679e5b2e14e20c8e0fb3bd50'


def evidence_names(binding):
    names=tuple(binding['files'])
    require(len(set(names))==37 and policy.previous.BASELINE in names and policy.RECEIPT in names
        and all(name.startswith('docs/implementation/evidence/') and name.endswith('.json')
            and '..' not in name.split('/') for name in names),'Retain the entire37-file genuine evidence closure')
    result=(*names,policy.BASELINE)
    require(len(set(result))==38,'Transfer exactly37 prior proofs plus this deployment binding')
    return result


def candidate(value,revision,new_manifest):
    require(value.get('profile')==policy.PROFILE and value.get('deployment_manifest_sha256')==OLD_MANIFEST
        and value['target']['deployment_commit']==FAILED_COMMIT,'Only the exact observed pending label attempt may be retargeted')
    require(re.fullmatch(r'[0-9a-f]{40}',revision) is not None and revision!=FAILED_COMMIT
        and re.fullmatch(r'sha256:[0-9a-f]{64}',new_manifest) is not None and new_manifest!=OLD_MANIFEST,
        'Require a distinct reviewed correction revision and manifest')
    policy.transition(value['source'],value['target'])
    result=deepcopy(value);result['target']['deployment_commit']=revision;result['deployment_manifest_sha256']=new_manifest
    policy.transition(result['source'],result['target'])
    return result


def unstarted(status):
    require(status=={'status':'Unstarted','state_exists':False,'hold_active':False,'plan_exists':False,'installed_binding':'source'},
        'Retarget only with no attempt journal, hold or plan and the original configuration still installed')


def guarded_plan(status,plan):
    unstarted(status)
    require(plan.get('status')=='Planned' and plan.get('schema_before')==plan.get('schema_after')==42
        and plan.get('same_current_database') is True and plan.get('database_cloned_or_migrated') is False
        and plan.get('services_restarted') is False
        and re.fullmatch(r'sha256:[0-9a-f]{64}',plan.get('plan_sha256','')) is not None,
        'The corrected plan must preserve the current42 database without restarting services')

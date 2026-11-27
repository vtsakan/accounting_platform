"""Static source and genuine history checks for the single billing-caption correction."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
MANIFEST='docs/implementation/evidence/CR012-LABEL-source.json'
BASELINE='docs/implementation/evidence/CR012-LABEL-operator-baseline.json'
REPORT='docs/implementation/evidence/CR012-LABEL-verification.json'
STATE='docs/implementation/state.md'
TEMPLATE='accounting/templates/accounting/agreement_list.html'
TEMPLATES=(TEMPLATE,'accounting/templates/accounting/entity_detail.html')
COMPLETED='63f6ad4d819b6579fddf1923ad56db8a2f105a50'  # pragma: allowlist secret -- actual published completed CR012 VM record
INSERT="{% elif agreement.billing_mode == 'ON_DEMAND' %}Χρεώσεις κατά περίπτωση"
ANCHOR='{% else %}Σε αναμονή επιλογής{% endif %}'


def require(value,message):
    if not value:raise RuntimeError(message)


def sha(data):return 'sha256:'+hashlib.sha256(data).hexdigest()


def regular(root,name):
    root=Path(root).resolve();path=root/name
    require(not Path(name).is_absolute() and '..' not in Path(name).parts and path.is_file()
        and not path.is_symlink() and path.resolve().is_relative_to(root),'Retain the regular source/history file: '+name)
    return path


def source_check():
    policy=json.loads(regular(ROOT,MANIFEST).read_text())
    require(policy['change']=='CR012-LABEL' and policy['status']=='Prepared' and policy['expected_suite']==1393
        and policy['financial_cases']==36 and policy['old_migrations']==42,
        'Retain the one-caption source scope and every existing application contract')
    require(len(policy['previous_prepared_files'])==996 and len(policy['previous_native_files'])==35,
        'Retain the exact completed CR012 source/history baseline')
    for name,expected in policy['previous_prepared_files'].items():
        actual=sha(regular(ROOT,name).read_bytes())
        require(actual==(policy['code_sha256'][name] if name in TEMPLATES else expected),
            'An undeclared previous prepared source file changed: '+name)
    for name,expected in policy['code_sha256'].items():
        require(sha(regular(ROOT,name).read_bytes())==expected,'Prepared caption-fix source changed: '+name)
    for name in TEMPLATES:
        template=regular(ROOT,name).read_text()
        require(template.count(INSERT)==template.count(ANCHOR)==1
            and sha(template.replace(INSERT,'').encode())==policy['previous_prepared_files'][name],
            'Only the explicit ON_DEMAND caption may change in each list/card; retain all existing branches')
    from verify_cr012 import test_methods
    require(sum(map(len,policy['original_test_methods'].values()))==1989,'Keep all1989 original method ASTs')
    for name,expected in policy['original_test_methods'].items():
        require(test_methods(regular(ROOT,name).read_text())==dict(expected),'An original native test method changed: '+name)
    require(len(policy['original_migration_files'])==42,'Keep every42 original migrations')
    for name,expected in policy['original_migration_files'].items():
        require(sha(regular(ROOT,name).read_bytes())==expected,'An original migration changed: '+name)
    import image
    context=image.candidate_context()[1]
    require(context['file_count']==409 and context['digest']==policy['application_context_digest'],
        'Use this exact new409-input image context')
    from preview_cr008_policy import unchanged_acceptances
    unchanged_acceptances(ROOT)
    return policy,context


def historical_files(root=ROOT):
    root=Path(root).resolve();policy=json.loads(regular(root,MANIFEST).read_text())
    require(subprocess.run(['git','merge-base','--is-ancestor',COMPLETED,'HEAD'],cwd=root,
        capture_output=True).returncode==0,'Retain the genuine completed CR012 native/VM history; never reconstruct it')
    files=policy['previous_native_files']
    require(len(files)==35,'Retain all35 actual historical receipts and bindings')
    for name,expected in files.items():
        raw=regular(root,name).read_bytes()
        require(sha(raw)==expected and subprocess.check_output(['git','show',COMPLETED+':'+name],cwd=root)==raw,
            'A genuine published historical receipt changed: '+name)
    instructions=sha(regular(root,'AGENTS.md').read_bytes())
    require(instructions==policy['operator_agents_sha256'],'Retain the actual operator AGENTS.md')
    return {'change':'CR012-LABEL','binding_schema':1,'previous_completed_vm_record':'git:'+COMPLETED,
        'files':files,'preserved_operator_files':{'AGENTS.md':instructions}}


def bind(root=ROOT):
    root=Path(root).resolve();value=historical_files(root);path=root/BASELINE
    if path.exists() or path.is_symlink():return check_binding(root)
    with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value


def check_binding(root=ROOT):
    root=Path(root).resolve();expected=historical_files(root)
    require(json.loads(regular(root,BASELINE).read_text())==expected,'The exclusive35-file label-fix binding changed; no refresh')
    return expected


def clean():
    require(not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip(),
        'Commit only the reviewed correction first; unrelated changes were retained')

"""Commit only a complete actual CR008 result and its exact generated state block."""
import json
from pathlib import Path
import re
import subprocess

from dev import ROOT
from cr008_receipts import BINDING,verify_binding

STATE='docs/implementation/state.md'
REPORT='docs/implementation/evidence/CR008-verification.json'


def state_result(report):
    return ('CR-008 source Prepared; operator technical gate Verified: '+str(report['suite']['tests_passed'])+
        ' tests, 36 financial cases, private classified attachments, real antivirus and encrypted file recovery passed; '
        'retained monthly-worker/ack-loss gate passed. VM/GitHub explicitly held on CR005 by user; '
        'browser/business acceptance and all 85 full acceptances remain Pending.')


def commit_actual_result(root=ROOT):
    root=Path(root).resolve()
    def git(*args):return subprocess.check_output(['git','-c','core.hooksPath=/dev/null',*args],cwd=root,text=True).strip()
    def need(ok,message):
        if not ok:raise RuntimeError(message)
    report=json.loads((root/REPORT).read_text());policy=json.loads((root/'docs/implementation/evidence/CR008-source.json').read_text())
    suite=report.get('suite',{});expected=policy['expected_suite'];baseline=verify_binding(root)
    need(report.get('change')=='CR-008' and report.get('status')=='Verified'
        and suite.get('tests_run')==suite.get('tests_passed')==expected
        and all(suite.get(k)==0 for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips'))
        and len(suite.get('cases',[]))==36 and all(r.get('outcome')=='passed' for r in suite['cases']),
        'Απαιτείται πλήρες πραγματικό αποτέλεσμα CR008.')
    need(report.get('source_commit')=='git:'+git('rev-parse','HEAD')
        and report.get('application_context_digest')==policy['application_context_digest']
        and report.get('actual_prior_receipt_files_sha256')==baseline['files'],
        'Η αναφορά δεν αντιστοιχεί στην τρέχουσα ελεγμένη πηγή.')
    need(type(report.get('production_suite_rerun')) is bool,
        'Απουσιάζει η ρητή καταγραφή επανάληψης ή διατήρησης της πραγματικής σουίτας.')
    if not report['production_suite_rerun']:
        from cr008_delivery_resume import load_retained_delivery
        delivery,proof=load_retained_delivery(policy,recording=True)
        need(report.get('retained_successful_delivery')==proof and report['suite']==delivery['suite']
            and report['image']['image_id']==proof['image_id']
            and report['image']['verification_revision']==report['source_commit'],
            'Δεν διατηρήθηκε η ακριβής επιτυχής αναφορά και η ίδια εικόνα.')
    scan=report.get('secret_scan',{})
    need(scan.get('scanner')=='detect-secrets' and scan.get('version')=='1.5.0'
        and scan.get('unreviewed_findings')==0,'Απουσιάζει νέος έλεγχος της τρέχουσας πηγής/ιστορίας.')
    need(all(report.get(k) is True for k in ('real_monthly_worker_and_commit_before_ack',
        'revocation_blocks_execution','second_scheduler_rejected','restricted_role_migrations',
        'historical_receipts_unchanged','docker_execution_by_operator','owned_resources_removed','vm_github_hold_by_user')),
        'Απουσιάζει υποχρεωτικός έλεγχος πραγματικής εκτέλεσης.')
    files=report.get('private_files',{})
    need(all(files.get(k) is True for k in ('original_file_sha256_after_authenticated_download','antivirus_real_eicar_denied',
        'scanner_unavailable_denied_without_storage','restricted_role_migrations','sealed_bytes_in_database',
        'all_public_tables_and_file_hashes_matched','wrong_recovery_key_denied','separate_external_recovery_material_used',
        'owned_resources_removed')),'Απουσιάζει πραγματικός έλεγχος αρχείων/επαναφοράς.')
    need(set(files.get('formats_verified',[]))=={'pdf','doc','docx','png','jpg','gif','webp','tif','bmp'},
        'Απουσιάζει επιτυχής πραγματικός τύπος συνημμένου.')
    need(all(report.get(k) is False for k in ('agent_native_execution','local_demo_or_vm_changed','github_updated','human_accounts_or_mfa_changed')),
        'Διαφέρει το επιτρεπόμενο πεδίο εκτέλεσης.')
    rows=subprocess.check_output(['git','status','--porcelain=v1','-z'],cwd=root,text=True).split('\0')
    need({r[3:] for r in rows if r}=={STATE,REPORT},'Υπάρχουν άλλες τοπικές αλλαγές. Δεν αποθηκεύτηκαν αυτόματα.')
    before=subprocess.check_output(['git','show','HEAD:'+STATE],cwd=root,text=True)
    pattern=r'(?s)(<!-- CR008-RESULT -->).*?(<!-- /CR008-RESULT -->)'
    expected_state,count=re.subn(pattern,lambda m:m[1]+'\n'+state_result(report)+'\n'+m[2],before,count=1)
    need(count==1 and (root/STATE).read_text()==expected_state,'Το αρχείο κατάστασης περιέχει επιπλέον αλλαγές.')
    git('add','--',STATE,REPORT)
    git('commit','-m','docs: record actual successful CR008 files and recovery verification','--',STATE,REPORT)
    need(not git('status','--porcelain'),'Υπάρχουν νέες τοπικές αλλαγές μετά την καταγραφή.')


if __name__=='__main__':
    try:commit_actual_result();print('Αποθηκεύτηκαν μόνο η πραγματική αναφορά CR008 και η ακριβής καταγραφή της.')
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:raise SystemExit('CR008 record stopped: '+str(error))

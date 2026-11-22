"""Reuse only the exact successful operator delivery observed in the console."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from dev import ROOT
import image

OBSERVATION='docs/implementation/evidence/CR008-files-runtime-failure.json'


def need(value,message):
    if not value:raise RuntimeError(message)


def context_at(revision):
    """Read a regular-file application manifest directly from a committed tree."""
    entries=subprocess.check_output(['git','ls-tree','-rz','--full-tree',revision],cwd=ROOT)
    files={}
    for entry in entries.split(b'\0'):
        if not entry:continue
        metadata,name=entry.split(b'\t',1);name=name.decode()
        if image.allowed(name):
            mode,kind,blob=metadata.decode().split()
            need(kind=='blob' and mode in {'100644','100755'},'Μη κανονικό αρχείο εφαρμογής στη δεσμευμένη πηγή.')
            files[name]=subprocess.check_output(['git','cat-file','blob',blob],cwd=ROOT)
    return image.archive(files)[1]


def load_retained_delivery(policy,*,recording=False):
    rows=subprocess.check_output(['git','status','--porcelain=v1','-z'],cwd=ROOT,text=True).split('\0')
    allowed={'docs/implementation/state.md','docs/implementation/evidence/CR008-verification.json'} if recording else set()
    need({row[3:] for row in rows if row}<=allowed,'Υπάρχουν άλλες τοπικές αλλαγές. Δεν επαναχρησιμοποιήθηκε η αναφορά.')
    expected=json.loads((ROOT/OBSERVATION).read_text())['successful_delivery']
    relative=Path(expected['retained_report_relative_path'])
    need(not relative.is_absolute() and '..' not in relative.parts,'Μη έγκυρη διαδρομή αναφοράς.')
    path=ROOT
    for part in relative.parts:
        path=path/part
        need(not path.is_symlink(),'Δεν επιτρέπεται συμβολικός σύνδεσμος στην πραγματική αναφορά.')
    need(path.is_file() and path.stat().st_size<=2_000_000,
        'Απουσιάζει η ακριβής ιδιωτική αναφορά1186/36. Χρησιμοποιήστε πλήρη έλεγχο χωρίς --resume-delivery.')
    raw=path.read_bytes();delivery=json.loads(raw)
    canonical='sha256:'+hashlib.sha256(json.dumps(delivery,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    need(canonical==expected['canonical_report_sha256'],
        'Η διατηρημένη αναφορά διαφέρει από το πραγματικό επιτυχές αποτέλεσμα. Δεν επαναχρησιμοποιήθηκε.')
    suite=delivery['suite'];selected=delivery['image'];context=selected['context']
    source=expected['source_commit'];image_id=expected['image_id']
    need(delivery.get('step')=='delivery' and delivery.get('status')=='Verified'
        and delivery.get('mode')=='docker-production-image' and delivery.get('docker_execution_this_step') is True
        and delivery.get('production_image_built_verified') is True,
        'Απαιτείται πραγματική επιτυχία της πλήρους εικόνας παραγωγής.')
    need(suite['tests_run']==suite['tests_passed']==policy['expected_suite']==1186
        and all(suite[k]==0 for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips'))
        and len(suite['cases'])==36 and all(row['outcome']=='passed' for row in suite['cases']),
        'Απαιτούνται οι πραγματικές1186 δοκιμές και36 οικονομικές περιπτώσεις.')
    need(context['digest']==policy['application_context_digest']==expected['application_context_digest']
        and context['file_count']==policy['application_inputs']==371 and selected['image_id']==image_id
        and selected['revision']==selected['verification_revision']==delivery['source_reference_commit']==source,
        'Η αναφορά δεν αντιστοιχεί στην επιτυχή εικόνα και πηγή του χειριστή.')
    revision=source.removeprefix('git:')
    need(subprocess.run(['git','merge-base','--is-ancestor',revision,'HEAD'],cwd=ROOT,capture_output=True).returncode==0,
        'Η πραγματική επιτυχής πηγή b493521e δεν είναι πρόγονος της τρέχουσας πηγής.')
    current=context_at('HEAD');original=context_at(revision)
    need(current==original==context==image.candidate_context()[1],
        'Τα αρχεία εφαρμογής άλλαξαν μετά την επιτυχία. Απαιτείται νέα πλήρης σουίτα.')
    proof={'report_path':relative.as_posix(),'report_sha256':'sha256:'+hashlib.sha256(raw).hexdigest(),
        'canonical_report_sha256':canonical,'source_commit':source,'image_id':image_id,
        'application_context_digest':context['digest'],'tests_passed':1186,'financial_cases':36}
    return delivery,proof


def scan_current_source(directory):
    """Fresh pinned static source/history scan; no application tests are rerun."""
    print('[CR008] Νέος έλεγχος πηγής και ιστορίας με δεσμευμένα εργαλεία.',flush=True)
    directory=Path(directory);environment=directory/'resume-tools'
    subprocess.run([sys.executable,'-m','venv',str(environment)],cwd=ROOT,capture_output=True,text=True,check=True)
    python=environment/'bin/python'
    subprocess.run([str(python),'-m','pip','--disable-pip-version-check','install','--timeout','120','--retries','5',
        '--require-hashes','--only-binary=:all:','--index-url','https://pypi.org/simple','-r',str(ROOT/'requirements-tools.txt')],
        cwd=ROOT,capture_output=True,text=True,check=True)
    result=subprocess.run([str(python),str(ROOT/'tools/scan_secrets.py')],cwd=ROOT,capture_output=True,text=True,check=True)
    scan=json.loads(result.stdout)
    need(scan.get('scanner')=='detect-secrets' and scan.get('version')=='1.5.0'
        and scan.get('unreviewed_findings')==0,'Ο νέος έλεγχος πηγής δεν ολοκληρώθηκε.')
    return scan

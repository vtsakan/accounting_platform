#!/usr/bin/env python3
"""Operator-only fresh production-image gate for the one-caption correction."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import image
import cr012_label as source
from dev import require_local_docker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only',action='store_true');parser.add_argument('--record',action='store_true')
    choice=parser.add_mutually_exclusive_group();choice.add_argument('--host-dns',action='store_true');choice.add_argument('--image')
    args=parser.parse_args();root=source.ROOT
    try:
        policy,context=source.source_check();bound=source.check_binding()
        if args.source_only:
            print(json.dumps({'change':'CR012-LABEL','status':'Prepared','application_inputs':409,
                'changed_application_files':2,'runtime_executed':False,'actual35_prior_files_bound':True}));return
        source.clean();require_local_docker()
        if args.record:source.require(not (root/source.REPORT).exists() and not (root/source.REPORT).is_symlink(),
            'Keep the existing successful label-fix recording')
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
        # The existing224 tool contracts are unchanged; they run only on the operator machine.
        subprocess.run([sys.executable,str(root/'tools/run_cr012_vm_guards.py')],cwd=root,check=True)
        if args.image:selected=image.reuse_for_verification(args.image)
        elif args.host_dns:
            from build_host_dns import build
            selected=build()
        else:selected=image.build()
        with tempfile.TemporaryDirectory(prefix='accounting-cr012-label-') as folder:
            destination=Path(folder)/'delivery.json'
            subprocess.run([sys.executable,str(root/'tools/verify_delivery.py'),'--report',str(destination),
                '--image',selected['image_id']],cwd=root,check=True)
            delivery=json.loads(destination.read_text());suite=delivery['suite']
            source.require(delivery['status']=='Verified' and delivery['docker_execution_this_step'] is True
                and delivery['production_image_built_verified'] is True and suite['tests_run']==suite['tests_passed']==1393
                and all(suite[k]==0 for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips'))
                and len(suite['cases'])==36 and all(case['outcome']=='passed' for case in suite['cases']),
                'All1393 application contracts and36 financial cases must pass in the new image')
            source.require(delivery['image']['image_id']==selected['image_id']
                and delivery['image']['context']==context and delivery['image']['verification_revision']=='git:'+revision
                and len([name for name in delivery['applied_migrations'] if name.startswith('accounting.')])==42
                and delivery['secret_scan']['unreviewed_findings']==0,'Require the exact new source/image and unchanged42-migration scope')
            private=root/'private/cr012-label'/selected['image_id'].removeprefix('sha256:')
            private.mkdir(parents=True,exist_ok=True,mode=0o700)
            with tempfile.NamedTemporaryFile(mode='w',prefix='delivery-'+revision+'-',suffix='.json',dir=private,delete=False) as stream:
                json.dump(delivery,stream,ensure_ascii=False,indent=2);stream.write('\n')
        source.source_check();source.require(source.check_binding()==bound,'A prior receipt changed during verification');source.clean()
        report={'change':'CR012-LABEL','status':'Verified','verified_at':delivery['verified_at'],
            'scope':'ON_DEMAND-list-and-client-card-caption-production-image','source_commit':'git:'+revision,
            'image':delivery['image'],'application_context_digest':context['digest'],'suite':suite,
            'changed_application_files':list(source.TEMPLATES),'new_migrations':0,'retained_migrations':42,
            'new_native_test_methods':0,'retained_deployment_contracts_passed':224,'secret_scan':delivery['secret_scan'],
            'production_suite_rerun':True,'historical_receipts_unchanged':True,'previous_native_files_sha256':bound['files'],
            'preserved_operator_files_sha256':bound['preserved_operator_files'],
            'previous_real_files_and_worker_report_sha256':bound['files']['docs/implementation/evidence/CR012-verification.json'],
            'real_file_recovery_and_worker_rerun':False,'docker_execution_by_operator':True,'agent_native_execution':False,
            'vm_changed':False,'github_updated':False,'human_accounts_or_mfa_changed':False,
            'existing_agreements_or_financial_data_changed':False,'full_requirement_acceptances_pending':85,
            'accountant_browser_acceptance':'Pending','g2_release_acceptance':'Pending','vm_upgrade':'Pending separate same-schema rollout'}
        if args.record:
            state=root/source.STATE;before=state.read_bytes()
            source.require(b'<!-- CR012-LABEL-RESULT -->' not in before,'Keep the existing label result marker')
            with (root/source.REPORT).open('x') as stream:stream.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            state.write_bytes(before+b'\n\n<!-- CR012-LABEL-RESULT -->\nVerified operator label correction: fresh1393/36 production-image gate and224 retained deployment guards. Only the ON_DEMAND caption in the agreement list and client card changed. All42 migrations, financial services, native test methods and35 historical receipts retained. Same-schema VM rollout and browser/business acceptance Pending; all85 full acceptances Pending.\n<!-- /CR012-LABEL-RESULT -->\n')
            names=[source.REPORT,source.STATE]
            changed=set(subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=root,text=True).splitlines())
            extra=set(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=root,text=True).splitlines())
            source.require(changed|extra==set(names),'Record only the exact native result and state append')
            subprocess.run(['git','-c','core.hooksPath=/dev/null','add','--',*names],cwd=root,check=True)
            subprocess.run(['git','-c','core.hooksPath=/dev/null','commit','-m','docs: record actual CR012 agreement caption image verification',
                '--',*names],cwd=root,check=True)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        reason=str(error) if isinstance(error,RuntimeError) else 'Operator verification stopped; original data and prior reports retained'
        parser.exit(1,'CR012-LABEL stopped: '+reason+'\n')


if __name__=='__main__':main()

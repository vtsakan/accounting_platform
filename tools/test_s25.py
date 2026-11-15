"""Operator-run planner contracts. No Django, database, Docker or network use."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from legacy_plan import afm, build_plan, cents, day, digest, positive_id, read_json
from legacy_restore import archive_versions, client_major, failure_category, redact, safe_error_lines, validate_server

FIXTURES = Path(__file__).resolve().parents[1]/'docs/implementation/fixtures'


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.source = read_json(FIXTURES/'s25-source.json')
        self.review = read_json(FIXTURES/'s25-review.json')

    def plan(self):
        self.review['source_sha256'] = digest(self.source)
        return build_plan(self.source,self.review)

    def state(self, plan, key):
        return next(e for e in plan['entries'] if e['key'] == key)

    def test_every_identity_has_a_disposition(self):
        plan = self.plan()
        self.assertTrue(plan['all_source_identities_covered'])
        self.assertEqual(plan['unresolved'],[])
        self.assertEqual(len(plan['entries']),32)
        self.assertFalse(plan['live_cutover_approved'])

    def test_exact_cash_opening_and_transfer_totals(self):
        expected = self.plan()['expected']['accounts']
        self.assertEqual(expected['cash_accounts:1'],dict(opening='120.00',balance='335.00',income='375.00',expense='120.00',transfer_in='0.00',transfer_out='40.00'))
        self.assertEqual(expected['cash_accounts:2']['balance'],'40.00')
        self.assertEqual(expected['cash_accounts:3']['balance'],'95.00')
        self.assertEqual(expected['cash_accounts:4']['balance'],'0.00')

    def test_zero_and_negative_cash_are_quarantined_without_abs_or_round(self):
        plan = self.plan()
        for key in ('transactions:8','transactions:9'):
            self.assertEqual(self.state(plan,key)['action'],'quarantine')
            self.assertNotIn(key,plan['expected']['cash'])
        self.assertEqual(self.source['transactions'][8]['amount'],'-5.00')

    def test_uuid_default_singleton_is_ordinary(self):
        plan = self.plan()
        self.assertFalse(plan['expected']['cash']['transactions:17']['transfer'])
        self.assertEqual(plan['transfers'],[['transactions:6','transactions:7']])

    def test_ambiguous_group_keeps_all_three_legs_in_quarantine(self):
        plan = self.plan()
        for key in ('transactions:11','transactions:12','transactions:13'):
            self.assertIn('ambiguous-transfer',self.state(plan,key)['issues'])

    def test_pair_requires_independent_supporting_reference(self):
        self.review['transfers'] = {}
        plan = self.plan()
        self.assertEqual(plan['transfers'],[])
        self.assertIn('transactions:6',plan['unresolved'])
        self.assertNotIn('transactions:7',plan['expected']['cash'])

    def test_pair_with_only_one_preopening_leg_is_not_half_imported(self):
        self.review['records']['cash_accounts:2']['opening']['date']='2026-01-07'
        plan = self.plan()
        self.assertEqual(plan['transfers'],[])
        self.assertEqual(self.state(plan,'transactions:6')['action'],'quarantine')
        self.assertEqual(self.state(plan,'transactions:7')['action'],'quarantine')

    def test_invalid_settlement_link_keeps_real_cash_without_allocation(self):
        plan = self.plan()
        self.assertEqual(self.state(plan,'transactions:10')['action'],'hold-unallocated')
        self.assertEqual(plan['expected']['cash']['transactions:10']['unallocated'],'25.00')

    def test_old_completed_status_does_not_settle_debt(self):
        plan = self.plan()
        self.assertEqual(self.source['agreements'][1]['status'],'COMPLETED')
        self.assertEqual(plan['expected']['charges']['agreements:2/0']['outstanding'],'20.00')
        self.assertEqual(plan['obligation_reconciliation']['agreements:2']['derived_state'],'OPEN')

    def test_raw_source_difference_is_explained_by_excluded_cash(self):
        plan=self.plan()
        for row in plan['raw_account_reconciliation'].values():
            self.assertEqual(row['unexplained_difference'],'0.00')
            self.assertEqual(row['unpriced_source_rows'],[])
        self.assertEqual(plan['raw_account_reconciliation']['cash_accounts:3']['raw_balance'],'110.00')
        self.assertEqual(plan['raw_account_reconciliation']['cash_accounts:3']['excluded_signed_cash'],'15.00')

    def test_credit_and_supplier_advance_are_source_bound(self):
        cash = self.plan()['expected']['cash']
        self.assertEqual(cash['transactions:3']['unallocated'],'50.00')
        self.assertEqual(cash['transactions:5']['unallocated'],'20.00')

    def test_unmapped_user_is_never_given_a_default_office(self):
        plan = self.plan()
        self.assertEqual(self.state(plan,'users:3')['action'],'quarantine')
        self.assertIn('unmapped-user',self.state(plan,'transactions:15')['issues'])
        self.assertNotIn('transactions:15',plan['expected']['cash'])

    def test_foreign_party_reference_denied(self):
        plan = self.plan()
        self.assertIn('foreign-or-missing-reference',self.state(plan,'transactions:14')['issues'])

    def test_opening_contains_precutoff_cash_once(self):
        plan = self.plan()
        self.assertEqual(self.state(plan,'transactions:1')['action'],'opening-component')
        self.assertNotIn('transactions:1',plan['expected']['cash'])
        self.assertEqual(plan['expected']['accounts']['cash_accounts:1']['opening'],'120.00')

    def test_wrong_opening_amount_is_unresolved(self):
        self.review['records']['cash_accounts:1']['opening']['amount']='100.00'
        self.assertIn('cash_accounts:1:opening-mismatch',self.plan()['unresolved'])

    def test_stale_source_hash_rejected(self):
        self.source['cash_accounts'][0]['name']='Άλλαξε μετά την ανασκόπηση'
        with self.assertRaises(ValueError):
            build_plan(self.source,self.review)

    def test_duplicate_identity_rejected(self):
        self.source['transactions'].append(copy.deepcopy(self.source['transactions'][0]))
        with self.assertRaises(ValueError):
            self.plan()

    def test_unknown_review_identity_rejected(self):
        self.review['records']['transactions:999']={}
        with self.assertRaises(ValueError):
            self.plan()

    def test_changed_lineage_rejected(self):
        self.review['lineage']='another-source'
        with self.assertRaises(ValueError):
            self.plan()

    def test_overallocation_rejected(self):
        self.review['records']['transactions:3']['allocations'][0]['amount']='150.00'
        with self.assertRaises(ValueError):
            self.plan()

    def test_cross_office_allocation_rejected(self):
        self.review['records']['transactions:3']['allocations'][0]['agreement']=3
        with self.assertRaises(ValueError):
            self.plan()

    def test_backdated_allocation_rejected(self):
        self.review['records']['transactions:3']['allocations'][0]['date']='2026-01-01'
        with self.assertRaises(ValueError):
            self.plan()

    def test_held_cash_cannot_be_settled(self):
        self.review['records']['transactions:10']['allocations']=[{'agreement':1,'charge':0,'amount':'1.00','date':'2026-01-10','reference':'SYNTHETIC'}]
        with self.assertRaises(ValueError):
            self.plan()

    def test_review_reference_required(self):
        self.review['records']['cash_accounts:1']['reference']=''
        plan = self.plan()
        self.assertIn('cash_accounts:1',plan['unresolved'])

    def test_quarantine_needs_recorded_reason(self):
        self.review['records']['transactions:8']['reason']=''
        self.assertIn('transactions:8',self.plan()['unresolved'])

    def test_no_implicit_import_of_blocked_master(self):
        self.review['records']['entities:1']['action']='quarantine'
        plan = self.plan()
        self.assertIn('blocked-master',self.state(plan,'transactions:2')['issues'])

    def test_category_cycle_quarantines_descendants(self):
        self.source['categories'][0]['parent_id']=2
        plan = self.plan()
        self.assertIn('category-cycle',self.state(plan,'categories:1')['issues'])
        self.assertEqual(self.state(plan,'categories:2')['action'],'quarantine')

    def test_named_human_approval_is_not_inferred(self):
        plan = self.plan()
        self.assertEqual(plan['financial_acceptance'],'Pending')
        self.assertEqual(plan['mode'],'synthetic')
        self.assertNotIn('reviewer_name',self.review)

    def test_money_denies_float_boolean_precision_nan_and_overflow(self):
        for value in (1.2,True,'1','1.2','1.230','NaN','Infinity','-0.01','0.00','10000000000.00'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                cents(value)
        self.assertEqual(str(cents('-10.00',signed=True)),'-10.00')

    def test_identifier_and_date_are_strict(self):
        for value in (True,1.5,'1',0,-1):
            with self.subTest(value=value),self.assertRaises(ValueError):
                positive_id(value)
        with self.assertRaises(ValueError):
            day('2026-2-01')

    def test_duplicate_json_keys_and_float_literals_are_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'review.json'
            for text in ('{"amount":"1.00","amount":"2.00"}','{"amount":1.1}','{"amount":NaN}'):
                path.write_text(text)
                with self.subTest(text=text),self.assertRaises(ValueError):
                    read_json(path)

    def test_afm_matches_s15_syntax_without_new_checksum_policy(self):
        self.assertEqual(afm(' EL １２３-４５６７８９ '),'123456789')
        self.assertEqual(afm(''),'')
        self.assertEqual(afm('000000000'),'000000000')
        with self.assertRaises(ValueError):
            afm('1234')

    def test_reviewed_finite_monthly_schedule(self):
        agreement = self.source['agreements'][0]
        agreement['start_date']='2026-01-15'; agreement['total_amount']='300.00'
        choice = self.review['records']['agreements:1']
        choice['billing_mode']='MONTHLY'
        choice['charges']=[{'amount':'150.00','date':'2026-01-15','due':'2026-01-31','period':'2026-01-01'},
            {'amount':'300.00','date':'2026-02-01','due':'2026-02-28','period':'2026-02-01'}]
        # Review cash as credit; the old references never automatically allocate.
        for key in ('transactions:2','transactions:3'):
            self.review['records'][key].pop('allocations')
        plan = self.plan()
        self.assertEqual(plan['expected']['charges']['agreements:1/0']['amount'],'150.00')
        self.assertEqual(plan['expected']['charges']['agreements:1/1']['amount'],'300.00')

    def test_partial_full_month_needs_review_instead_of_automatic_proration(self):
        choice=self.review['records']['agreements:1'];choice['billing_mode']='MONTHLY'
        choice['charges'][0].update(amount='10.00',period='2026-01-01')
        self.review['records']['transactions:2'].pop('allocations')
        self.review['records']['transactions:3'].pop('allocations')
        plan=self.plan()
        self.assertEqual(self.state(plan,'agreements:1')['action'],'quarantine')


class RestoreContractTests(unittest.TestCase):
    def server(self):
        return {'database':'s25_raw_'+'a'*20,'user':'postgres','version':170011,
            'port':5432,'read_only':'off','user_tables':0}

    def test_client_and_archive_versions_parsed_independently(self):
        self.assertEqual(client_major('pg_restore (PostgreSQL) 17.11 (Debian)'),17)
        toc='; Dumped from database version: 15.20\n; Dumped by pg_dump version: 17.11\n'
        self.assertEqual(archive_versions(toc),{'source_major':15,'dumped_by_major':17})

    def test_missing_archive_version_is_not_assumed(self):
        with self.assertRaises(ValueError):
            archive_versions('; Dumped from database version: 15.20')
        with self.assertRaises(ValueError):
            client_major('unrelated output')

    def test_empty_writable_expected_target_accepted(self):
        info=self.server()
        validate_server(info,database=info['database'],user='postgres',major=17)

    def test_wrong_server_role_database_or_nonempty_target_denied(self):
        original=self.server()
        for field,value in [('database','accounting_platform'),('user','another_role'),('version',150020),
                ('version',True),('port',5433),('read_only','on'),('user_tables',1)]:
            info={**original,field:value}
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                validate_server(info,database=original['database'],user='postgres',major=17)

    def test_restore_failure_categories_do_not_suppress_errors(self):
        for text,expected in [('pg_restore: error: could not seek in input file','archive-seek-or-block'),
                ('ERROR: unrecognized configuration parameter','unsupported-server-setting'),
                ('ERROR: duplicate key value violates unique constraint','constraint'),
                ('No space left on device','disk-capacity'),('unrecognised new error','unclassified')]:
            with self.subTest(expected=expected):
                self.assertEqual(failure_category(text),expected)

    def test_secrets_redacted_before_private_or_public_output(self):
        secret='example-'+'a'*40
        raw='pg_restore: error: authentication failed '+secret
        self.assertNotIn(secret,redact(raw,[secret]))
        self.assertNotIn(secret,'\n'.join(safe_error_lines(raw,[secret])))

    def test_public_headers_exclude_sql_and_detail_values(self):
        text='pg_restore: error: could not execute query: ERROR: relation "private_name" already exists\nDETAIL: synthetic-value\nCommand was: INSERT INTO x VALUES (\'private-value\');'
        headers='\n'.join(safe_error_lines(text,[]))
        self.assertIn('already exists',headers)
        for private in ('private_name','synthetic-value','private-value','INSERT INTO'):
            self.assertNotIn(private,headers)

    def test_headers_are_bounded(self):
        self.assertEqual(len(safe_error_lines('\n'.join('pg_restore: error: '+'x'*2000 for _ in range(8)),[])),3)
        self.assertTrue(all(len(line)<=500 for line in safe_error_lines('pg_restore: error: '+'x'*2000,[])))

    def restore_runner(self, directory, *, fail=False):
        from legacy_migration import Runner
        class Fake(Runner):
            def __init__(self):
                self.work=Path(directory);self.nonce='a'*20;self.pg15='owned-15';self.pg17='owned-17'
                self.stage='logical-15-to-17';self.admin_password='synthetic-admin'
                self.values={'DB_PASSWORD':'synthetic-app'};self.report_dir=self.work
                self.calls=[];self.restore_context=None
            def own(self,*args):
                return {}
            def psql(self,*args,**kwargs):
                return json.dumps({'database':'s25_raw_'+self.nonce,'user':'postgres','version':170011,
                    'port':5432,'read_only':'off','user_tables':0})
            def docker(self,*args,**kwargs):
                self.calls.append((args,kwargs))
                if '--version' in args:
                    return b'pg_restore (PostgreSQL) 17.11',0,b''
                if '--list' in args:
                    return b'; Dumped from database version: 15.20\n; Dumped by pg_dump version: 17.11\n',0,b''
                if 'sha256sum' in args:
                    data=next(kwargs['data'] for cmd,kwargs in self.calls if 's25-archive-copy' in cmd)
                    return (hashlib.sha256(data).hexdigest()+'  '+args[-1]+'\n').encode(),0,b''
                if '--single-transaction' in args and fail:
                    raise RuntimeError('synthetic restore failure')
                return b'',0,b''
        return Fake()

    def test_restore_uses_seekable_tmpfs_file_explicit_target_and_atomic_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=self.restore_runner(directory);path=Path(directory)/'forward.dump';path.write_bytes(b'PGDMPsynthetic')
            runner.restore(runner.pg17,'s25_raw_'+runner.nonce,path)
            calls=[args for args,_ in runner.calls]
            restore=next(args for args in calls if '--single-transaction' in args)
            self.assertIn('--exit-on-error',restore);self.assertIn('--host',restore)
            self.assertIn('127.0.0.1',restore);self.assertNotIn('--interactive',restore)
            self.assertTrue(restore[-1].startswith('/s25-recovery/'))
            self.assertEqual(calls[-1][4:7],('rm','-f','--'))
            self.assertEqual(runner.stage,'logical-15-to-17')

    def test_failure_keeps_restore_exception_and_removes_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=self.restore_runner(directory,fail=True);path=Path(directory)/'forward.dump';path.write_bytes(b'PGDMPsynthetic')
            with self.assertRaisesRegex(RuntimeError,'synthetic restore failure'):
                runner.restore(runner.pg17,'s25_raw_'+runner.nonce,path)
            self.assertEqual(runner.calls[-1][0][4:7],('rm','-f','--'))

    def test_non_owned_database_name_is_rejected_before_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=self.restore_runner(directory)
            with self.assertRaises(ValueError):
                runner.restore(runner.pg17,'accounting_demo_retained',Path(directory)/'missing.dump')
            self.assertEqual(runner.calls,[])

    def test_invalid_archive_header_is_rejected_before_db_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=self.restore_runner(directory);path=Path(directory)/'wrong.dump';path.write_bytes(b'not-a-custom-archive')
            with self.assertRaises(ValueError):
                runner.restore(runner.pg17,'s25_raw_'+runner.nonce,path)
            self.assertEqual(runner.calls,[])

    def test_tmpfs_transfer_preserves_binary_bytes_without_docker_cp_or_tty(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=self.restore_runner(directory);path=Path(directory)/'forward.dump'
            payload=b'PGDMP\x00\xff\x80\r\n\x00synthetic';path.write_bytes(payload)
            runner.restore(runner.pg17,'s25_raw_'+runner.nonce,path)
            writes=[(args,kwargs) for args,kwargs in runner.calls if 's25-archive-copy' in args]
            self.assertEqual(len(writes),1)
            args,kwargs=writes[0]
            self.assertEqual(kwargs['data'],payload)
            self.assertIn('--interactive',args);self.assertNotIn('--tty',args)
            self.assertIn('sh',args);self.assertIn('set -C; umask 077; exec cat > "$1"',args)
            self.assertTrue(args[-1].startswith('/s25-recovery/'))
            self.assertFalse(any(args[0]=='cp' for args,_ in runner.calls))
            self.assertTrue(runner.restore_context['archive_bytes_match'])

    def test_failed_tmpfs_write_does_not_start_restore_and_still_cleans_file(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=self.restore_runner(directory);path=Path(directory)/'forward.dump';path.write_bytes(b'PGDMPsynthetic')
            original=runner.docker
            def failed(*args,**kwargs):
                if 's25-archive-copy' in args:
                    raise RuntimeError('synthetic tmpfs write failure')
                return original(*args,**kwargs)
            runner.docker=failed
            with self.assertRaisesRegex(RuntimeError,'synthetic tmpfs write failure'):
                runner.restore(runner.pg17,'s25_raw_'+runner.nonce,path)
            self.assertFalse(any('--single-transaction' in args for args,_ in runner.calls))
            self.assertEqual(runner.calls[-1][0][4:7],('rm','-f','--'))

    def test_changed_transferred_bytes_stop_before_sql_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=self.restore_runner(directory);path=Path(directory)/'forward.dump';path.write_bytes(b'PGDMPsynthetic')
            original=runner.docker
            def changed(*args,**kwargs):
                if 'sha256sum' in args:return b'wrong-checksum',0,b''
                return original(*args,**kwargs)
            runner.docker=changed
            with self.assertRaises(ValueError):
                runner.restore(runner.pg17,'s25_raw_'+runner.nonce,path)
            self.assertFalse(any('--single-transaction' in args for args,_ in runner.calls))
            self.assertFalse(runner.restore_context['archive_bytes_match'])
            self.assertEqual(runner.calls[-1][0][4:7],('rm','-f','--'))

    def test_docker_and_shell_error_headers_remain_visible_and_redacted(self):
        text='Error response from daemon: cannot write "private-path"\nsh: 1: cannot create "private-path": Read-only file system\nDETAIL: excluded-value'
        headers='\n'.join(safe_error_lines(text,[]))
        self.assertIn('Error response from daemon:',headers);self.assertIn('Read-only file system',headers)
        self.assertNotIn('private-path',headers);self.assertNotIn('excluded-value',headers)
        self.assertEqual(failure_category(text),'private-mount-write')


if __name__ == '__main__':
    unittest.main()
